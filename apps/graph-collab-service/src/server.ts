import Fastify from "fastify";
import cors from "@fastify/cors";
import { WebSocketServer, type WebSocket } from "ws";
import {
  compileSkill,
  dedupCandidates,
  llmDedup,
  dryRunSkill,
  godNodes,
  isDestructiveRun,
  orphanRescuer,
  analyzeCorpus,
  auditNodeDates,
  buildGraph,
  buildTimeline,
  createLLM,
  deriveSchema,
  extractJson,
  rankScenarios,
  scenarioById,
  FACTMETA_KEY,
  heuristicExtractor,
  liveAt,
  lightRagExtractor,
  materializeAt,
  type Message,
  parseDocuments,
  planSkillRun,
  DEFAULT_PARSE,
  type BuildDocument,
  type ParseConfig,
  type ProjectMeta,
  resolveScopeNodes,
  surpriseEdges,
  type Axis,
  type Bucket,
  type QuantSegment,
  type JournalOp,
  type Layer,
  type LayerDef,
  type SkillScope,
  type SkillTier,
} from "@graphcraft/core";
import type { ClientMessage, ServerMessage } from "@graphcraft/shared";
import path from "node:path";
import { spawn } from "node:child_process";
import { GraphStore, ConcurrentEditError, NotFoundError } from "./store.js";
import { ProjectStore } from "./project-store.js";
import { SetupStore, type SetupPatch } from "./setup-store.js";
import { Room } from "./room.js";
import { renderGraph } from "./render.js";

// Node's global fetch (undici) ignores HTTP(S)_PROXY unless NODE_USE_ENV_PROXY=1
// is set at startup — easy to miss when the server is launched outside the npm
// scripts, and it surfaces as a bare "fetch failed" 500 on every LLM call.
// Install a ProxyAgent dispatcher here so outbound fetch honors the proxy
// regardless of how the process was launched.
{
  const proxyUrl =
    process.env.HTTPS_PROXY ?? process.env.https_proxy ??
    process.env.HTTP_PROXY ?? process.env.http_proxy;
  if (proxyUrl) {
    try {
      const { ProxyAgent, setGlobalDispatcher } = await import("undici");
      setGlobalDispatcher(new ProxyAgent(proxyUrl));
    } catch (e) {
      console.warn("[proxy] failed to install dispatcher:", (e as Error).message);
    }
  }
}

// allow the LLM key via a file path (DSKEY_FILE) — sandbox blocks `$(...)` in
// the launch command, so we read it here instead of inlining the secret.
if (!process.env.DEEPSEEK_API_KEY && process.env.DSKEY_FILE) {
  try {
    const fs = await import("node:fs");
    process.env.DEEPSEEK_API_KEY = fs.readFileSync(process.env.DSKEY_FILE, "utf8").trim();
  } catch {
    /* no key file */
  }
}

const PORT = Number(process.env.COLLAB_PORT ?? 4001);
const GRAPHS_DIR = process.env.GRAPHS_DIR ?? "./graphs";
const PROJECTS_DIR = process.env.PROJECTS_DIR ?? path.join(path.dirname(path.resolve(GRAPHS_DIR)), "projects");

const store = new GraphStore(GRAPHS_DIR);
const projects = new ProjectStore(PROJECTS_DIR);
const setups = new SetupStore();

// ── server-driven assist (option) ──────────────────────────────────────────
// When ASSIST_CMD is set, the UI's POST /assist makes the hub spawn a headless
// Claude (e.g. `claude -c -p "$GC_ASSIST_PROMPT"`) on state change, instead of
// relying on an external long-poll loop. Off by default. The built prompt is
// passed via the GC_ASSIST_PROMPT env var (no shell-escaping of the prompt).
//   ASSIST_CMD       shell command, default "" (disabled).
//                    recommended: claude -c -p "$GC_ASSIST_PROMPT" \
//                      --allowedTools mcp__graphcraft__get_slice \
//                      mcp__graphcraft__search_nodes mcp__graphcraft__propose \
//                      mcp__graphcraft__suggest_questions
//   ASSIST_CWD       working dir (must contain .mcp.json), default process.cwd()
//   ASSIST_DEBOUNCE_MS  coalesce rapid changes, default 1500
const ASSIST_CMD = process.env.ASSIST_CMD ?? "";
const ASSIST_CWD = process.env.ASSIST_CWD ?? process.cwd();
const ASSIST_DEBOUNCE_MS = Number(process.env.ASSIST_DEBOUNCE_MS ?? "1500");
const assistRunning = new Set<string>(); // graphId → a claude is in flight
const assistTimers = new Map<string, ReturnType<typeof setTimeout>>();
const assistSig = new Map<string, string>(); // last (panel+nodes) we acted on

function buildAssistPrompt(graphId: string, panel: string, nodeIds: string[]): string {
  const sel = nodeIds.length ? `Selected node id(s): ${nodeIds.join(", ")}.` : `Nothing is selected.`;
  let task: string;
  if (panel === "rag") {
    task = nodeIds.length
      ? `The human opened the RAG panel with a selection. Push 3-5 insightful questions about the selected node(s) via the graphcraft MCP \`suggest_questions\` tool (seedNodeIds = the selection).`
      : `The human opened the RAG panel with nothing selected. Look at the graph's hubs (god_nodes) and push 3-5 broad, insightful questions the graph can answer via \`suggest_questions\`.`;
  } else {
    task = nodeIds.length
      ? `The human opened the Curation panel with a selection. Inspect the selected node(s) with the graphcraft MCP (get_slice / search_nodes), find concrete curation actions (merge duplicates, fix a wrong type, etc.) and push them with the \`propose\` tool.`
      : `The human opened the Curation panel with NOTHING selected — they want graph-wide curation. Scan the graph (god_nodes, search_nodes for likely duplicate names) and \`propose\` the 3-5 most valuable curation actions (e.g. merge duplicate entities, fix wrong types). Do not require a selection.`;
  }
  return [
    `You are assisting a human curating GraphCraft graph "${graphId}".`,
    sel,
    task,
    `Act directly against graphId "${graphId}" — do not ask the human anything. Keep all text in English. When done, exit.`,
  ].join(" ");
}

// spawn a headless Claude (ASSIST_CMD wrapper) with a prompt + context env.
function spawnClaude(prompt: string, env: Record<string, string>, onExit?: () => void) {
  const child = spawn(ASSIST_CMD, {
    shell: true,
    cwd: ASSIST_CWD,
    stdio: "ignore",
    env: { ...process.env, GC_ASSIST_PROMPT: prompt, ...env },
  });
  const done = () => onExit?.();
  child.on("exit", done);
  child.on("error", done);
}

function triggerAssist(graphId: string, panel: string, nodeIds: string[]): { ok: boolean; reason: string } {
  if (!ASSIST_CMD) return { ok: false, reason: "disabled (set ASSIST_CMD to enable)" };
  if (!panel) return { ok: false, reason: "no panel open" }; // selection optional (curation w/o selection = graph-wide)
  const sig = `${panel}:${[...nodeIds].sort().join(",")}`;
  if (assistSig.get(graphId) === sig && assistRunning.has(graphId)) return { ok: false, reason: "duplicate" };
  // debounce: coalesce a burst of changes into one spawn
  clearTimeout(assistTimers.get(graphId));
  assistTimers.set(
    graphId,
    setTimeout(() => {
      assistTimers.delete(graphId);
      if (assistRunning.has(graphId)) return; // single-flight per graph
      assistRunning.add(graphId);
      assistSig.set(graphId, sig);
      spawnClaude(buildAssistPrompt(graphId, panel, nodeIds), { GC_GRAPH: graphId, GC_PANEL: panel, GC_NODES: nodeIds.join(",") }, () =>
        assistRunning.delete(graphId),
      );
    }, ASSIST_DEBOUNCE_MS),
  );
  return { ok: true, reason: "scheduled" };
}

// the RAG console accepts both QUESTIONS and find/highlight COMMANDS; the hub
// spawns a headless Claude to either answer (answer_question) or locate +
// highlight (search_nodes + focus_view), then post a short answer.
function buildRagPrompt(graphId: string, questionId: string, question: string): string {
  return [
    `You are the assistant for GraphCraft graph "${graphId}".`,
    `A human wrote this in the RAG console: "${question.replace(/"/g, "'")}".`,
    `If it is a COMMAND to find / highlight / show entities: use search_nodes (and get_slice if useful) to locate the node ids, call focus_view with those ids to highlight them on everyone's canvas, then call answer_question with graphId "${graphId}", questionId "${questionId}", a one-line summary, and the entities you highlighted.`,
    `If it is a QUESTION about the graph: answer it from the graph (search_nodes / get_slice / god_nodes) and call answer_question with graphId "${graphId}", questionId "${questionId}", the answer text, and the entities you used.`,
    `Always finish by calling answer_question so the human's console turn resolves. Keep it in English. Do not ask anything; act and exit.`,
  ].join(" ");
}

function triggerRag(graphId: string, questionId: string, question: string) {
  if (!ASSIST_CMD) return;
  spawnClaude(buildRagPrompt(graphId, questionId, question), { GC_GRAPH: graphId, GC_PANEL: "rag-ask", GC_NODES: "", GC_QID: questionId });
}

// ── room + client registry ──
interface Client {
  socket: WebSocket;
  actor: string;
}
const clients = new Map<string, Set<Client>>();
const rooms = new Map<string, Room>();

// RAG inbox: questions humans ask in the console, answered by the agent (Claude)
// over MCP — no server-side LLM call. The agent polls pending and pushes answers
// back, which broadcast into every console. `config` carries the asker's
// last-selected retrieval scope (algorithm/model + date/kinds/selection toggles).
interface RagQuestion {
  id: string;
  question: string;
  by: string;
  config: Record<string, unknown>;
  askedAt: string;
  status: "pending" | "answered";
  answer?: string;
  entities?: { id: string; name: string }[];
  paths?: string[];
  sources?: { id: string; documentId: string | null; text: string }[];
}
const ragInbox = new Map<string, RagQuestion[]>();

function broadcast(graphId: string, msg: ServerMessage): void {
  const set = clients.get(graphId);
  if (!set) return;
  const data = JSON.stringify(msg);
  for (const c of set) {
    if (c.socket.readyState === c.socket.OPEN) c.socket.send(data);
  }
}

// point-to-point: deliver a message to one actor's socket(s) only (used by the
// "see what they see" peek request/response so big position payloads don't fan
// out to everyone).
function sendToActor(graphId: string, actor: string, msg: ServerMessage): void {
  const set = clients.get(graphId);
  if (!set) return;
  const data = JSON.stringify(msg);
  for (const c of set) {
    if (c.actor === actor && c.socket.readyState === c.socket.OPEN) c.socket.send(data);
  }
}

async function getRoom(graphId: string): Promise<Room> {
  let room = rooms.get(graphId);
  if (!room) {
    room = new Room(graphId, store, (m) => broadcast(graphId, m));
    await room.init();
    rooms.set(graphId, room);
  }
  return room;
}

// Presence GC: drop humans whose WS socket is gone (sockets that died without a
// clean "close"), and agents whose heartbeat lapsed. Keeps the avatar list real.
const AGENT_TTL_MS = Number(process.env.PRESENCE_AGENT_TTL_MS ?? "30000");
setInterval(() => {
  for (const [graphId, room] of rooms) {
    const live = new Set<string>();
    for (const c of clients.get(graphId) ?? [])
      if (!c.actor.startsWith("agent:") && c.socket.readyState === c.socket.OPEN) live.add(c.actor);
    const n = room.pruneStale(live, AGENT_TTL_MS);
    if (n) console.log(`[presence-gc] ${graphId}: pruned ${n} stale participant(s)`);
  }
}, 10000).unref?.();

const COLORS = ["#ea4335", "#4f86f7", "#34a853", "#a142f4", "#ff7043", "#00acc1"];
const colorFor = (actor: string) => {
  let h = 0;
  for (const ch of actor) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return COLORS[h % COLORS.length]!;
};

// ── HTTP ──
const app = Fastify({ logger: false, bodyLimit: 64 * 1024 * 1024 });
await app.register(cors, { origin: true, credentials: true });

app.get("/health", async () => ({ ok: true }));

app.get("/api/graphs", async () => store.listGraphs());

const slug = (s: string) =>
  s.toLowerCase().trim().replace(/[^a-z0-9а-я]+/gi, "-").replace(/^-+|-+$/g, "").slice(0, 40);

function pickExtractor(useLlm?: boolean) {
  const llm = useLlm ? createLLM() : null;
  // LLM path uses the faithful LightRAG module (typed entities + relations);
  // keyless heuristic only as the offline fallback.
  return { extractor: llm ? lightRagExtractor(llm, { gleanings: 1 }) : heuristicExtractor, provider: llm?.provider ?? null };
}

// Exploration: profile the first batch on a sample → detected entity kinds +
// a draft schema, so the wizard can recommend a config before the full build.
app.post("/api/graphs/profile", async (req, reply) => {
  const b = req.body as { documents?: BuildDocument[]; llm?: boolean };
  if (!b?.documents?.length) return reply.code(400).send({ error: "profile needs { documents: [{text}] }" });
  const sample = b.documents.slice(0, 5).map((d) => ({ ...d, text: (d.text ?? "").slice(0, 4000) }));
  const { extractor, provider } = pickExtractor(b.llm);
  const { state } = await buildGraph({ graphId: "__profile__", documents: sample, extractor, layout: false });
  const types: Record<string, number> = {};
  for (const n of state.nodes) if (n.layer !== "chunk" && n.layer !== "community") types[n.type] = (types[n.type] ?? 0) + 1;
  return {
    provider,
    sampledDocs: sample.length,
    entityCount: Object.values(types).reduce((a, c) => a + c, 0),
    types,
    schema: deriveSchema(state),
  };
});

// Create a new graph from its first stream batch (full build).
app.post("/api/graphs", async (req, reply) => {
  const b = req.body as { id?: string; name?: string; language?: string; documents?: BuildDocument[]; llm?: boolean; chunkSize?: number; overlap?: number };
  if (!b?.documents?.length) return reply.code(400).send({ error: "create needs { documents: [{text}] }" });
  const existing = new Set((await store.listGraphs()).map((m) => m.id));
  let id = b.id || slug(b.name ?? "") || "graph";
  if (existing.has(id)) { let i = 2; while (existing.has(`${id}-${i}`)) i++; id = `${id}-${i}`; }
  const { extractor } = pickExtractor(b.llm);
  const { state, meta } = await buildGraph({
    graphId: id,
    name: b.name || id,
    language: b.language,
    documents: b.documents,
    extractor,
    chunkSize: b.chunkSize,
    chunkOverlap: b.overlap,
  });
  await store.saveGraph(meta, state);
  return { id, meta };
});

// ── projects (corpora): own the source + parsing; graphs are variants ──
const uniqueId = (base: string, taken: Set<string>) => {
  let id = base || "x";
  if (taken.has(id)) { let i = 2; while (taken.has(`${id}-${i}`)) i++; id = `${id}-${i}`; }
  return id;
};

app.get("/api/projects", async () => {
  const list = await projects.list();
  const graphs = await store.listGraphs();
  const withCounts = list.map((p) => ({ ...p, graphCount: graphs.filter((g) => g.projectId === p.id).length }));
  // legacy bucket: graphs created before the project layer
  const orphans = graphs.filter((g) => !g.projectId);
  if (orphans.length)
    withCounts.push({ id: "_legacy", name: "Legacy graphs", createdAt: "", parse: DEFAULT_PARSE, documentCount: 0, graphCount: orphans.length } as ProjectMeta & { graphCount: number });
  return withCounts;
});

app.post("/api/projects", async (req, reply) => {
  const b = req.body as { name?: string; parse?: Partial<ParseConfig>; files?: { uri: string; text: string }[]; source?: string };
  if (!b?.files?.length) return reply.code(400).send({ error: "project needs { files: [{uri,text}] }" });
  const parse: ParseConfig = { ...DEFAULT_PARSE, ...(b.parse ?? {}) };
  const documents = parseDocuments(b.files, parse);
  const taken = new Set((await projects.list()).map((p) => p.id));
  const id = uniqueId(slug(b.name ?? "") || "project", taken);
  const meta: ProjectMeta = {
    id, name: b.name || id, createdAt: new Date().toISOString(), parse, source: b.source ?? null, documentCount: documents.length,
  };
  return projects.create(meta, documents);
});

app.get("/api/projects/:p", async (req, reply) => {
  const { p } = req.params as { p: string };
  const meta = await projects.get(p);
  if (!meta) return reply.code(404).send({ error: `project ${p} not found` });
  const graphs = (await store.listGraphs()).filter((g) => g.projectId === p);
  return { ...meta, graphs };
});

app.get("/api/projects/:p/documents", async (req) => {
  const { p } = req.params as { p: string };
  const docs = await projects.documents(p);
  return { total: docs.length, sample: docs.slice(0, 40) };
});

// create a graph variant over the project's parsed corpus
app.post("/api/projects/:p/graphs", async (req, reply) => {
  const { p } = req.params as { p: string };
  const proj = await projects.get(p);
  if (!proj) return reply.code(404).send({ error: `project ${p} not found` });
  const b = req.body as { name?: string; language?: string; llm?: boolean };
  const documents = await projects.documents(p);
  if (!documents.length) return reply.code(400).send({ error: "project has no documents" });
  const taken = new Set((await store.listGraphs()).map((g) => g.id));
  const id = uniqueId(slug(b.name ?? "") || `${p}-graph`, taken);
  const { extractor } = pickExtractor(b.llm);
  const { state, meta } = await buildGraph({
    graphId: id, name: b.name || id, language: b.language ?? (proj.parse.format === "chat" ? "ru" : undefined),
    documents, extractor, chunkSize: proj.parse.chunkSize, chunkOverlap: proj.parse.chunkOverlap,
  });
  await store.saveGraph({ ...meta, projectId: p }, state);
  return { id };
});

// day-2 at the project level: parse new files into the source, reconcile into
// every graph variant of the project.
app.post("/api/projects/:p/ingest", async (req, reply) => {
  const { p } = req.params as { p: string };
  const proj = await projects.get(p);
  if (!proj) return reply.code(404).send({ error: `project ${p} not found` });
  const b = req.body as { files?: { uri: string; text: string }[]; llm?: boolean };
  if (!b?.files?.length) return reply.code(400).send({ error: "ingest needs { files: [{uri,text}] }" });
  const delta = parseDocuments(b.files, proj.parse);
  await projects.addDocuments(p, delta);
  const { extractor } = pickExtractor(b.llm);
  const graphs = (await store.listGraphs()).filter((g) => g.projectId === p);
  const reports: Record<string, unknown> = {};
  for (const g of graphs) {
    const { state: deltaState } = await buildGraph({ graphId: g.id, documents: delta, extractor, chunkSize: proj.parse.chunkSize, chunkOverlap: proj.parse.chunkOverlap, layout: false });
    const r = await store.ingestDelta(g.id, deltaState);
    await (await getRoom(g.id)).reload();
    reports[g.id] = { added: r.added.length, linked: r.linked.length, conflicts: r.conflicts.length, autoMerges: r.journalEntries.length };
  }
  return { documents: delta.length, graphs: reports };
});

// delete a graph (dir + caches + live room)
app.delete("/api/graphs/:id", async (req) => {
  const { id } = req.params as { id: string };
  rooms.delete(id);
  clients.delete(id);
  await store.deleteGraph(id);
  return { ok: true };
});

// delete a project and all its graph variants
app.delete("/api/projects/:p", async (req) => {
  const { p } = req.params as { p: string };
  const graphs = (await store.listGraphs()).filter((g) => g.projectId === p);
  for (const g of graphs) {
    rooms.delete(g.id);
    clients.delete(g.id);
    await store.deleteGraph(g.id);
  }
  await projects.delete(p);
  return { ok: true, deletedGraphs: graphs.length };
});

// ── AI-led setup flow (pre-graph): analyze corpus → propose scenarios → build ──
// One short-lived session per project, shared by the UI and the /graphcraft
// agent (MCP). The agent leads (analyze + recommend + notes); the human confirms.
async function runAnalyze(projectId: string, goal: string, llm?: boolean) {
  const proj = await projects.get(projectId);
  if (!proj) return null;
  const docs = await projects.documents(projectId);
  const session = setups.ensure(projectId);
  session.status = "analyzing";
  setups.set(session);
  // sample build → detected entity kinds. LightRAG by default (typed kinds);
  // falls back to the keyless heuristic automatically when no LLM key is set.
  const sample = docs.slice(0, 8).map((d) => ({ ...d, text: (d.text ?? "").slice(0, 4000) }));
  const { extractor, provider } = pickExtractor(llm ?? true);
  const { state } = sample.length
    ? await buildGraph({ graphId: "__setup__", documents: sample, extractor, layout: false })
    : { state: { nodes: [], edges: [], journal: [] } };
  const types: Record<string, number> = {};
  for (const n of state.nodes) if (n.layer !== "chunk" && n.layer !== "community") types[n.type] = (types[n.type] ?? 0) + 1;

  const profile = analyzeCorpus(docs, { format: proj.parse.format, entityTypes: types, provider, chunkSize: proj.parse.chunkSize });
  const scenarios = rankScenarios(profile, goal);
  session.goal = goal;
  session.profile = profile;
  session.scenarios = scenarios;
  session.status = "ready";
  if (!session.selectedScenarioId)
    session.selectedScenarioId = scenarios.find((s) => s.recommended)?.scenario.id ?? scenarios[0]?.scenario.id ?? null;
  if (!session.confirmedTypes.length) session.confirmedTypes = Object.keys(types);
  const sel = scenarioById(session.selectedScenarioId ?? "");
  if (sel) {
    session.extractor = sel.build.extractor;
    session.communities = sel.view.communities;
    session.axis = sel.view.axis;
    if (!session.graphName) session.graphName = `${proj.name} · ${sel.title}`;
  }
  return setups.set(session);
}

app.post("/api/projects/:p/setup/analyze", async (req, reply) => {
  const { p } = req.params as { p: string };
  const b = (req.body ?? {}) as { goal?: string; llm?: boolean };
  const session = await runAnalyze(p, b.goal ?? "", b.llm);
  if (!session) return reply.code(404).send({ error: `project ${p} not found` });
  return session;
});

app.get("/api/projects/:p/setup", async (req) => {
  const { p } = req.params as { p: string };
  return setups.get(p) ?? setups.ensure(p);
});

app.patch("/api/projects/:p/setup", async (req) => {
  const { p } = req.params as { p: string };
  const body = (req.body ?? {}) as SetupPatch;
  const session = setups.patch(p, body);
  // selecting a scenario re-seeds the view/extractor defaults for keys the
  // caller didn't explicitly set (so the human starts from a sane preset).
  if (body.selectedScenarioId) {
    const sel = scenarioById(body.selectedScenarioId);
    if (sel) {
      if (body.extractor === undefined) session.extractor = sel.build.extractor;
      if (body.communities === undefined) session.communities = sel.view.communities;
      if (body.axis === undefined) session.axis = sel.view.axis;
      setups.set(session);
    }
  }
  return session;
});

app.post("/api/projects/:p/setup/note", async (req) => {
  const { p } = req.params as { p: string };
  const b = (req.body ?? {}) as { by?: string; text?: string; step?: number };
  return setups.addNote(p, b.by ?? "agent:claude", b.text ?? "", b.step);
});

app.post("/api/projects/:p/setup/build", async (req, reply) => {
  const { p } = req.params as { p: string };
  const proj = await projects.get(p);
  if (!proj) return reply.code(404).send({ error: `project ${p} not found` });
  const session = setups.get(p);
  if (!session?.profile) return reply.code(400).send({ error: "run analyze first" });
  const documents = await projects.documents(p);
  if (!documents.length) return reply.code(400).send({ error: "project has no documents" });
  session.status = "building";
  setups.set(session);
  const scenario = scenarioById(session.selectedScenarioId ?? "");
  const { extractor } = pickExtractor(session.extractor === "lightrag");
  const taken = new Set((await store.listGraphs()).map((g) => g.id));
  const id = uniqueId(slug(session.graphName) || `${p}-graph`, taken);
  const { state, meta } = await buildGraph({
    graphId: id,
    name: session.graphName || id,
    language: proj.parse.format === "chat" ? "ru" : undefined,
    documents,
    extractor,
    chunkSize: proj.parse.chunkSize,
    chunkOverlap: proj.parse.chunkOverlap,
    resolution: scenario?.build.resolution,
    minCooccurrence: scenario?.build.minCooccurrence,
  });
  await store.saveGraph(
    {
      ...meta,
      projectId: p,
      ...(scenario
        ? { scenario: { id: scenario.id, title: scenario.title, axis: session.axis, communities: session.communities, types: session.confirmedTypes } }
        : {}),
    },
    state,
  );
  session.status = "done";
  session.builtGraphId = id;
  setups.set(session);
  return { id, scenario: scenario?.id ?? null };
});

// ── setup chat assistant (DeepSeek via createLLM) ──
const SETUP_SYSTEM = `You are the GraphCraft setup assistant. GraphCraft turns a stream of documents (plain text or chat logs) into a knowledge graph: entities, relations, communities and facts, each traceable to its source chunk.

You help the user configure how their knowledge graph ("graphrag") will be built, guiding them through these steps and answering questions:
1) Source — the user adds text/files and states a goal.
2) Scenario — a ready preset of HOW the graph works, matched to the goal. Available scenarios:
   • team-map — Team & ownership map (PERSON/TEAM/ORG/TASK; who works on what).
   • timeline — Project timeline (EPIC/STORY/TASK/EVENT on a time axis).
   • clients — Clients & commitments (CLIENT/ORG/CONTRACT).
   • themes — Knowledge themes (interpretable community clusters with summaries).
   • risks — Risks & blockers (blocks / depends_on chains).
3) Entities & relations — confirm the detected entity kinds.
4) Layers & communities — toggle community zones; pick the time axis (tx = recorded, valid = real-world).
5) Extraction model — LightRAG (LLM: typed entities + named relations) or keyless (fast offline heuristic).
6) Summary & build.

Rules:
- Be concise and concrete. ALWAYS reply in the user's language.
- Recommend a specific scenario by its human title, grounded in the goal and the corpus profile given in context.
- Use only the provided context; never invent data. If the corpus is empty or tiny, say so and suggest adding a source.
- Explain choices in plain words; the human makes the final click — you advise, you don't execute.
- Keep answers to a few sentences unless asked for detail.`;

function setupContext(s: ReturnType<typeof setups.get>): string {
  if (!s) return "";
  const p = s.profile;
  const lines: string[] = [`Goal: ${s.goal || "(not stated)"}`];
  if (p) {
    lines.push(`Corpus: ${p.docCount} docs, ~${p.estChunks} chunks, langs ${p.languages.map((l) => l.lang).join("/")}`);
    if (p.timeSpan.from) lines.push(`Time span: ${p.timeSpan.from}..${p.timeSpan.to} (${p.timeSpan.dated} dated)`);
    if (p.authors.length) lines.push(`Authors: ${p.authors.slice(0, 6).map((a) => `${a.name}(${a.count})`).join(", ")}`);
    const kinds = Object.entries(p.entityTypes);
    if (kinds.length) lines.push(`Entity kinds: ${kinds.map(([k, v]) => `${k}:${v}`).join(", ")}`);
    if (p.topTerms.length) lines.push(`Top terms: ${p.topTerms.slice(0, 10).map((t) => t.term).join(", ")}`);
  }
  if (s.scenarios?.length) lines.push(`Ranked scenarios: ${s.scenarios.map((x) => `${x.scenario.id}${x.recommended ? "*" : ""}(${x.score.toFixed(2)})`).join(", ")}`);
  lines.push(`Current: scenario=${s.selectedScenarioId ?? "-"}, types=[${s.confirmedTypes.join(",")}], extractor=${s.extractor}, communities=${s.communities}, axis=${s.axis}, step=${s.step}`);
  return "Setup context:\n" + lines.join("\n");
}

async function chatReply(
  contextText: string,
  history: Message[],
  text: string,
): Promise<{ reply: string | null; provider: string | null }> {
  const llm = createLLM();
  if (!llm) return { reply: null, provider: null };
  const messages: Message[] = [
    { role: "system", content: SETUP_SYSTEM },
    ...(contextText ? [{ role: "system" as const, content: contextText }] : []),
    ...history.slice(-10),
    { role: "user", content: text },
  ];
  const { text: reply } = await llm.complete(messages, { temperature: 0.3, maxTokens: 500 });
  return { reply, provider: llm.provider };
}

const NO_LLM_NOTE = "⚙️ Чат-ассистент не настроен — задайте DEEPSEEK_API_KEY. / Assistant not configured: set DEEPSEEK_API_KEY.";

// project-scoped chat: stores the user message + the assistant reply as notes
app.post("/api/projects/:p/setup/chat", async (req, reply) => {
  const { p } = req.params as { p: string };
  const b = (req.body ?? {}) as { text?: string; step?: number };
  if (!b.text?.trim()) return reply.code(400).send({ error: "chat needs { text }" });
  const s0 = setups.get(p) ?? setups.ensure(p);
  const history: Message[] = (s0.assistantNotes ?? []).map((n) => ({ role: n.by.startsWith("agent") ? "assistant" : "user", content: n.text }));
  const { reply: ans, provider } = await chatReply(setupContext(s0), history, b.text);
  setups.addNote(p, "user:anon", b.text, b.step);
  setups.addNote(p, provider ? `agent:${provider}` : "agent:assistant", ans ?? NO_LLM_NOTE, b.step);
  return setups.get(p);
});

// project-less chat (before the project exists): stateless, returns the reply
app.post("/api/setup/chat", async (req) => {
  const b = (req.body ?? {}) as { text?: string; history?: Message[] };
  if (!b.text?.trim()) return { reply: null, provider: null };
  return chatReply("", b.history ?? [], b.text);
});

// ── Graph-RAG: ask a question, answered from the graph (MS-GraphRAG style) ──
const RAG_SYS = `You answer questions using ONLY the provided knowledge-graph context (entities, relationships, community reports and source excerpts) from a knowledge graph. Ground every claim in the context; if it doesn't contain the answer, say so. Cite the entities/communities you used. Answer concisely in the SAME language as the question.`;

// Generic stopwords (EN + a few RU). Without this, tokens like "the/are/many/
// how" substring-match almost every node and swamp the term-overlap ranking
// with noise seeds, starving the real answer entities out of the context.
const STOPWORDS = new Set([
  "the", "are", "and", "for", "with", "that", "this", "from", "have", "has", "had",
  "was", "were", "how", "many", "much", "who", "whom", "whose", "what", "which",
  "when", "where", "why", "does", "did", "any", "some", "there", "their", "they",
  "them", "about", "into", "over", "than", "then", "been", "being",
  "mentioned", "mention", "named", "name", "podcast", "episode", "episodes",
  "что", "как", "кто", "где", "когда", "почему", "сколько", "или", "для", "это", "эти",
]);

// Crude de-pluralisation so a query token matches inflected forms living in the
// graph ("banks" → "bank", which then hits "Alfa-Bank" and "Bank where…").
// Guarded to keep stems ≥3 chars so we don't over-truncate short words.
const stem = (t: string) => {
  const s = t.replace(/(ies|es|s)$/i, (m) => (m.toLowerCase() === "ies" ? "y" : ""));
  return s.length >= 3 ? s : t;
};

const qTerms = (q: string) =>
  [...new Set((q.toLowerCase().match(/[\p{L}\p{N}]{3,}/gu) ?? []))].filter((t) => !STOPWORDS.has(t));

const ALGO_HINT: Record<string, string> = {
  lightrag: "Retrieval = LightRAG (local entity neighbourhoods + global community reports).",
  "ms-graphrag": "Retrieval = MS GraphRAG (global: community reports first, then their entities).",
  tog: "Retrieval = Think-on-Graph (reasoning paths walked across relations from the question's seed entities).",
};

type GraphState = Awaited<ReturnType<typeof store.getState>>;
interface RetrieveOpts {
  algorithm?: "lightrag" | "ms-graphrag" | "tog";
  useDate?: boolean; useKinds?: boolean; useSelection?: boolean;
  selection?: string[];
  view?: { from?: string | null; to?: string | null; types?: string[]; axis?: "tx" | "valid" };
}

// Deterministic graph retrieval shared by BOTH RAG flows: the direct server-LLM
// `/ask` AND the agent-routed (Claude-subscription) console. Returns the
// reasoning chain (paths), the entities to highlight, the source chunks
// (provenance) and a ready-made LLM context. This is what makes ToG produce a
// real reasoning chain + highlight + citations regardless of who writes the prose.
function retrieve(state: GraphState, question: string, opts: RetrieveOpts) {
  const algo = opts.algorithm ?? "lightrag";
  const byId = new Map(state.nodes.map((n) => [n.id, n]));
  const terms = qTerms(question);
  const hit = (s: string | null | undefined) => {
    if (!s) return 0;
    const l = s.toLowerCase();
    return terms.reduce((a, t) => a + (l.includes(t) || l.includes(stem(t)) ? 1 : 0), 0);
  };
  // Category questions ("how many banks", "which companies") name a type rather
  // than an entity; reward nodes whose type matches a (singularised) query term.
  const typeHit = (ty: string) => {
    const t = ty.toLowerCase();
    return terms.some((q) => { const s = stem(q); return s.length >= 3 && (t.includes(s) || t.includes(q)); }) ? 1 : 0;
  };
  const deg = new Map<string, number>();
  for (const e of state.edges) if (!e.invalidation) {
    deg.set(e.sourceId, (deg.get(e.sourceId) ?? 0) + 1);
    deg.set(e.targetId, (deg.get(e.targetId) ?? 0) + 1);
  }

  // ── scope filters (date window / kinds / selection) ──
  const ax: "tx" | "valid" = opts.view?.axis === "valid" ? "valid" : "tx";
  const wf = opts.useDate && opts.view?.from ? Date.parse(opts.view.from) : null;
  const wt = opts.useDate && opts.view?.to ? Date.parse(opts.view.to) : null;
  const kinds = opts.useKinds && opts.view?.types?.length ? new Set(opts.view.types) : null;
  const sel = opts.useSelection && opts.selection?.length ? new Set(opts.selection) : null;
  const inScope = (n: (typeof state.nodes)[number]) => {
    if (n.layer === "chunk" || n.layer === "community") return false;
    if (kinds && !kinds.has(n.type)) return false;
    if (sel && !sel.has(n.id)) return false;
    if (wf != null || wt != null) {
      const t = Date.parse(((ax === "valid" ? n.validFrom : n.txFrom) ?? "") as string);
      if (Number.isNaN(t)) return false;
      if (wf != null && t < wf) return false;
      if (wt != null && t > wt) return false;
    }
    return true;
  };
  const candidates = state.nodes.filter(inScope);
  const scopeIds = new Set(candidates.map((n) => n.id));

  // seeds = best term-matched candidate entities (+ degree tiebreak)
  const ranked = candidates
    .map((n) => ({ n, s: hit(n.name) * 3 + hit(n.summary) + typeHit(n.type) * 2 + Math.min(2, (deg.get(n.id) ?? 0) / 20) }))
    .sort((a, c) => c.s - a.s);
  // Keep all term-matched candidates (up to the context's own 24-entity cap)
  // rather than truncating at 12 — aggregation questions ("how many banks")
  // need recall across every match, not just the top dozen.
  const seeds = (ranked.filter((x) => x.s > 0).length ? ranked.filter((x) => x.s > 0) : ranked).slice(0, 20).map((x) => x.n);

  const used = new Map<string, (typeof state.nodes)[number]>();
  for (const n of seeds) used.set(n.id, n);
  const paths: string[] = [];
  let comms: (typeof state.nodes)[number][] = [];

  if (algo === "tog") {
    // Think-on-Graph: walk reasoning paths from seeds across relations in scope.
    const adj = new Map<string, { to: string; rel: string | null }[]>();
    for (const e of state.edges) if (!e.invalidation && e.type === "entity_relation" && scopeIds.has(e.sourceId) && scopeIds.has(e.targetId)) {
      (adj.get(e.sourceId) ?? adj.set(e.sourceId, []).get(e.sourceId)!).push({ to: e.targetId, rel: e.relation ?? null });
      (adj.get(e.targetId) ?? adj.set(e.targetId, []).get(e.targetId)!).push({ to: e.sourceId, rel: e.relation ?? null });
    }
    let frontier = seeds.slice(0, 6).map((n) => n.id);
    for (let depth = 0; depth < 2 && used.size < 26; depth++) {
      const next: string[] = [];
      for (const f of frontier) {
        const nbrs = (adj.get(f) ?? []).sort((a, c) => hit(byId.get(c.to)?.name) - hit(byId.get(a.to)?.name)).slice(0, 4);
        for (const nb of nbrs) {
          if (paths.length < 40) paths.push(`${byId.get(f)?.name} —${nb.rel ?? "rel"}→ ${byId.get(nb.to)?.name}`);
          if (!used.has(nb.to) && used.size < 26) { used.set(nb.to, byId.get(nb.to)!); next.push(nb.to); }
        }
      }
      frontier = next;
    }
  } else {
    // lightrag + ms-graphrag: pull community reports whose members are in scope
    comms = state.nodes
      .filter((n) => n.layer === "community")
      .map((n) => ({ n, s: hit(n.name) + hit(n.summary) }))
      .sort((a, c) => c.s - a.s)
      .slice(0, algo === "ms-graphrag" ? 8 : 5)
      .filter((x) => x.s > 0 || x.n.summary)
      .map((x) => x.n);
    // ms-graphrag: bring in member entities of the top communities (global→local)
    if (algo === "ms-graphrag") {
      const top = new Set(comms.map((c) => c.id));
      for (const e of state.edges) if (e.type === "member_of" && top.has(e.targetId) && scopeIds.has(e.sourceId) && used.size < 26)
        used.set(e.sourceId, byId.get(e.sourceId)!);
    }
    // relationships among used entities
    for (const e of state.edges) {
      if (paths.length >= 40) break;
      if (!e.invalidation && e.type === "entity_relation" && used.has(e.sourceId) && used.has(e.targetId))
        paths.push(`${byId.get(e.sourceId)?.name} —${e.relation ?? "rel"}→ ${byId.get(e.targetId)?.name}`);
    }
  }

  const usedArr = [...used.values()];
  const usedIds = new Set(usedArr.map((n) => n.id));
  // provenance: chunks mentioning the used entities
  const chunkIds = new Set<string>();
  for (const e of state.edges) if (e.type === "mentioned_in" && usedIds.has(e.sourceId)) chunkIds.add(e.targetId);
  const sources = [...chunkIds].slice(0, 8).map((cid) => {
    const c = byId.get(cid);
    const a = (c?.attributes ?? {}) as Record<string, unknown>;
    return { id: cid, documentId: (a.documentId as string) ?? c?.name ?? null, text: String(a.text ?? "").slice(0, 600) };
  }).filter((s) => s.text);

  const context = [
    comms.length ? "Community reports:\n" + comms.map((c) => `# ${c.name}\n${c.summary ?? ""}`).join("\n") : "",
    usedArr.length ? "Entities:\n" + usedArr.slice(0, 24).map((n) => `- ${n.name} (${n.type})${n.summary ? ": " + n.summary : ""}`).join("\n") : "",
    paths.length ? "Relationships / reasoning paths:\n" + paths.join("\n") : "",
    sources.length ? "Source excerpts:\n" + sources.map((s, i) => `[${i + 1}] ${s.documentId}: ${s.text}`).join("\n\n") : "",
  ].filter(Boolean).join("\n\n");

  return {
    algorithm: algo,
    usedEntities: usedArr.slice(0, 26).map((n) => ({ id: n.id, name: n.name })),
    usedCommunities: comms.map((c) => ({ id: c.id, name: c.name })),
    paths,
    sources,
    context,
  };
}

app.post("/api/graphs/:id/ask", async (req, reply) => {
  const { id } = req.params as { id: string };
  const b = (req.body ?? {}) as RetrieveOpts & { question?: string; model?: string };
  if (!b.question?.trim()) return reply.code(400).send({ error: "ask needs { question }" });
  const llm = createLLM();
  if (!llm) return { answer: NO_LLM_NOTE, sources: [], provider: null, usedEntities: [], usedCommunities: [], paths: [] };

  const state = await store.getState(id);
  const r = retrieve(state, b.question, b);
  const model = b.model || llm.model || "default";
  let text: string;
  try {
    ({ text } = await llm.complete(
      [
        { role: "system", content: RAG_SYS + " " + (ALGO_HINT[r.algorithm] ?? "") },
        { role: "user", content: `Context:\n${r.context}\n\nQuestion: ${b.question}` },
      ],
      { temperature: 0.2, maxTokens: 800, ...(b.model ? { model: b.model } : {}) },
    ));
  } catch (e) {
    // Surface the real cause (e.g. "fetch failed" = proxy/network) as a clean
    // 502 instead of a bare 500, so the console shows an actionable message.
    const msg = (e as Error).message;
    req.log.error({ err: e, provider: llm.provider, model }, "ask: LLM call failed");
    return reply.code(502).send({
      error: `LLM call failed (${llm.provider}/${model}): ${msg}`,
      provider: llm.provider,
      model,
    });
  }
  return {
    answer: text,
    provider: llm.provider,
    model,
    algorithm: r.algorithm,
    usedEntities: r.usedEntities,
    usedCommunities: r.usedCommunities,
    paths: r.paths,
    sources: r.sources,
  };
});

const parseLayers = (s?: string): Layer[] | undefined => {
  const xs = (s ?? "").split(",").map((v) => v.trim()).filter(Boolean) as Layer[];
  return xs.length ? xs : undefined;
};
const parseAxis = (s?: string): Axis => (s === "valid" ? "valid" : "tx");

app.get("/api/graph/:id", async (req, reply) => {
  const { id } = req.params as { id: string };
  const { layers, types, asOf, axis, projections, from, to } = req.query as { layers?: string; types?: string; asOf?: string; axis?: string; projections?: string; from?: string; to?: string };
  try {
    const [state, meta] = await Promise.all([store.getState(id), store.getMeta(id)]);
    const render = renderGraph(state, meta, {
      layers: parseLayers(layers),
      types: (types ?? "").split(",").map((s) => s.trim()).filter(Boolean) || undefined,
      asOf: asOf || null,
      axis: parseAxis(axis),
      projections: projections === "1" || projections === "true",
      from: from || null,
      to: to || null,
    });
    return { ...render, version: meta.version, meta };
  } catch (e) {
    if (e instanceof NotFoundError) return reply.code(404).send({ error: String(e.message) });
    throw e;
  }
});

app.get("/api/graphs/:id/journal", async (req) => {
  const { id } = req.params as { id: string };
  return (await store.getState(id)).journal;
});

// activity timeline (heatmap buckets) for the scrubber, per axis
app.get("/api/graphs/:id/timeline", async (req) => {
  const { id } = req.params as { id: string };
  const { axis, bucket, segments } = req.query as { axis?: string; bucket?: string; segments?: string };
  let segs: QuantSegment[] | undefined;
  try { segs = segments ? (JSON.parse(segments) as QuantSegment[]) : undefined; } catch { segs = undefined; }
  return buildTimeline(await store.getState(id), parseAxis(axis), { bucket: (bucket as Bucket | "auto") || "auto", segments: segs });
});

app.get("/api/graphs/:id/suggestions", async (req) => {
  const { id } = req.params as { id: string };
  return (await getRoom(id)).listSuggestions();
});

// the graph's data model (JSON-Schema-shaped) — stored or derived from data
app.get("/api/graphs/:id/schema", async (req) => {
  const { id } = req.params as { id: string };
  return store.getSchema(id);
});
app.put("/api/graphs/:id/schema", async (req) => {
  const { id } = req.params as { id: string };
  await store.saveSchema(id, req.body as Parameters<typeof store.saveSchema>[1]);
  return store.getSchema(id);
});
app.post("/api/graphs/:id/schema/derive", async (req) => {
  const { id } = req.params as { id: string };
  return store.deriveAndSaveSchema(id);
});

// Day-2 ingestion: build a delta from new documents, reconcile against the
// curated graph (respecting prior merges + verified facts), broadcast resync.
app.post("/api/graphs/:id/ingest", async (req, reply) => {
  const { id } = req.params as { id: string };
  const body = req.body as { documents?: BuildDocument[]; llm?: boolean; chunkSize?: number; overlap?: number };
  if (!body?.documents?.length) return reply.code(400).send({ error: "ingest needs { documents: [{text}] }" });
  const { extractor } = pickExtractor(body.llm);
  const { state: delta } = await buildGraph({
    graphId: id,
    documents: body.documents,
    extractor,
    chunkSize: body.chunkSize,
    chunkOverlap: body.overlap,
    layout: false,
  });
  const report = await store.ingestDelta(id, delta);
  await (await getRoom(id)).reload();
  return {
    addedNodes: report.added.length,
    addedEdges: report.addEdges.length,
    linked: report.linked,
    conflicts: report.conflicts,
    autoMerges: report.journalEntries.length,
  };
});

// layer registry (canonical + emergent) with live counts
app.get("/api/graphs/:id/layers", async (req) => {
  const { id } = req.params as { id: string };
  return store.getLayers(id);
});

// define/update a layer in the registry (annotation; no version bump)
app.post("/api/graphs/:id/layers", async (req, reply) => {
  const { id } = req.params as { id: string };
  const def = req.body as LayerDef;
  if (!def?.name || typeof def.granularity !== "number") {
    return reply.code(400).send({ error: "layer requires { name, granularity }" });
  }
  await store.defineLayer(id, def);
  return store.getLayers(id);
});

app.post("/api/graphs/:id/ops", async (req, reply) => {
  const { id } = req.params as { id: string };
  const body = req.body as { op: JournalOp; payload: Record<string, unknown>; actor?: string };
  const room = await getRoom(id);
  try {
    return await room.applyOp(body.actor ?? "user:anon", body.op, body.payload);
  } catch (e) {
    if (e instanceof ConcurrentEditError) return reply.code(409).send({ error: e.message });
    return reply.code(400).send({ error: String((e as Error).message) });
  }
});

app.post("/api/graphs/:id/revert", async (req) => {
  const { id } = req.params as { id: string };
  const body = (req.body ?? {}) as { actor?: string };
  return (await getRoom(id)).revertLast(body.actor ?? "user:anon");
});

app.post("/api/graphs/:id/pin", async (req) => {
  const { id } = req.params as { id: string };
  const body = req.body as { nodeIds: string[]; pinned: boolean };
  await (await getRoom(id)).pin(body.nodeIds, body.pinned);
  return { ok: true };
});

// agent presence — registers "agent:claude" as a room participant
app.post("/api/graphs/:id/presence/agent", async (req) => {
  const { id } = req.params as { id: string };
  const body = (req.body ?? {}) as { actor?: string; name?: string };
  const actor = body.actor ?? "agent:claude";
  const room = await getRoom(id);
  room.join({ actor, name: body.name ?? actor, color: colorFor(actor), kind: "agent" });
  return { ok: true, version: room.currentVersion };
});

// who's in the room and what they're looking at — node ids enriched with names
// so an agent can "see what the human sees" (selection, timeline instant,
// active filters, on-canvas visible slice).
async function enrichPresence(id: string) {
  const room = await getRoom(id);
  const state = await store.getState(id);
  const nameOf = new Map(state.nodes.map((n) => [n.id, n.name] as const));
  const ref = (nid: string) => ({ id: nid, name: nameOf.get(nid) ?? null });
  const participants = room.listParticipants().map((p) => {
    const v = p.view ?? {};
    const visible = v.visibleNodeIds ?? [];
    return {
      actor: p.actor,
      name: p.name,
      kind: p.kind,
      selection: (v.selectedNodeIds ?? []).map(ref),
      selectedEdgeId: v.selectedEdgeId ?? null,
      focused: (p.focusedNodeIds ?? []).map(ref),
      panel: v.panel ?? null,
      timeline: { asOf: v.asOf ?? null, axis: v.axis ?? null },
      filters: { layers: v.layers ?? [], types: v.types ?? [] },
      visible: { count: visible.length, sample: visible.slice(0, 50).map(ref) },
    };
  });
  return { graphId: id, version: room.currentVersion, rev: room.presenceRev, participants };
}

app.get("/api/graphs/:id/presence", async (req) => {
  const { id } = req.params as { id: string };
  return enrichPresence(id);
});

// long-poll: block until presence changes past `since` (or ~25s timeout), then
// return the enriched snapshot + current rev. Lets an agent react in <100ms
// instead of polling. Client loops: read rev, then wait?since=rev.
app.get("/api/graphs/:id/presence/wait", async (req) => {
  const { id } = req.params as { id: string };
  const since = Number((req.query as { since?: string }).since ?? "-1");
  const room = await getRoom(id);
  if (room.presenceRev <= since) await room.waitForPresenceChange(25000);
  return enrichPresence(id);
});

// agent proposes candidate questions for the human's RAG console (chips).
app.post("/api/graphs/:id/questions", async (req) => {
  const { id } = req.params as { id: string };
  const b = (req.body ?? {}) as {
    by?: string;
    questions: { text: string; rationale?: string; seedNodeIds?: string[] }[];
  };
  const by = b.by ?? "agent:claude";
  const now = new Date().toISOString();
  const qs = (b.questions ?? [])
    .filter((q) => q?.text?.trim())
    .map((q) => ({
      id: crypto.randomUUID(),
      text: q.text.trim(),
      rationale: q.rationale,
      seedNodeIds: q.seedNodeIds ?? [],
      by,
      createdAt: now,
    }));
  const all = (await getRoom(id)).addQuestions(qs);
  return { added: qs.length, questions: all };
});

app.get("/api/graphs/:id/questions", async (req) => {
  const { id } = req.params as { id: string };
  return (await getRoom(id)).listQuestions();
});

// date audit for a node's card: flag implausible date ranges on its facts
// (incident relationship edges + the node's own lifespan) and propose shifting
// the left or right boundary. Fixes apply via the existing edit_edge op.
app.get("/api/graphs/:id/nodes/:nid/date-issues", async (req) => {
  const { id, nid } = req.params as { id: string; nid: string };
  const state = await store.getState(id);
  const node = state.nodes.find((n) => n.id === nid);
  if (!node) return { nodeId: nid, facts: [] };
  const nodesById = new Map(state.nodes.map((n) => [n.id, n] as const));
  const facts = auditNodeDates(node, state.edges, nodesById, { nowIso: new Date().toISOString() });
  const flagged = facts.filter((f) => f.issues.length);
  return { nodeId: nid, name: node.name, facts, flaggedCount: flagged.length };
});

// the UI pings this on a state change (panel + selection); if ASSIST_CMD is set
// the hub spawns a headless Claude to generate suggestions/questions itself —
// a server-driven alternative to the external long-poll loop. No-op (and 200)
// when disabled, so the UI can always call it.
app.post("/api/graphs/:id/assist", async (req) => {
  const { id } = req.params as { id: string };
  const b = (req.body ?? {}) as { panel?: string; nodeIds?: string[] };
  const r = triggerAssist(id, b.panel ?? "", b.nodeIds ?? []);
  return { ...r, enabled: !!ASSIST_CMD };
});

// command the canvas to center/highlight a slice
app.post("/api/graphs/:id/focus", async (req) => {
  const { id } = req.params as { id: string };
  const body = req.body as { nodeIds: string[]; note?: string; by?: string };
  (await getRoom(id)).focus(body.by ?? "agent:claude", body.nodeIds, body.note);
  return { ok: true };
});

// a human asks a question in the RAG console → enqueue for the agent (Claude)
// to answer over MCP, and broadcast it so it shows (pending) in every console.
app.post("/api/graphs/:id/rag-questions", async (req, reply) => {
  const { id } = req.params as { id: string };
  const body = (req.body ?? {}) as { question?: string; by?: string; config?: Record<string, unknown> };
  if (!body.question?.trim()) return reply.code(400).send({ error: "rag-questions needs { question }" });
  await getRoom(id); // ensure the room exists so connected clients receive it
  const q: RagQuestion = {
    id: crypto.randomUUID(),
    question: body.question,
    by: body.by ?? "user",
    config: body.config ?? {},
    askedAt: new Date().toISOString(),
    status: "pending",
  };
  // Precompute the deterministic graph retrieval (algorithm-specific) NOW, with
  // the asker's config. Claude writes the prose, but the reasoning chain (paths),
  // the highlighted entities and the source chunks come from here — otherwise the
  // agent flow shows none of them (e.g. ToG had no chain / highlight / citations).
  try {
    const state = await store.getState(id);
    const r = retrieve(state, q.question, (body.config ?? {}) as RetrieveOpts);
    q.entities = r.usedEntities;
    q.paths = r.paths;
    q.sources = r.sources;
  } catch { /* no graph / no LLM context → agent answers free-form */ }
  const inbox = ragInbox.get(id) ?? ragInbox.set(id, []).get(id)!;
  inbox.push(q);
  broadcast(id, { type: "rag_ask", id: q.id, question: q.question, by: q.by });
  // server-driven: let a headless Claude answer the question or run the
  // find/highlight command (no-op when ASSIST_CMD is unset).
  triggerRag(id, q.id, q.question);
  return q;
});

// the agent polls pending questions (with the asker's retrieval config).
app.get("/api/graphs/:id/rag-questions", async (req) => {
  const { id } = req.params as { id: string };
  const { status } = (req.query ?? {}) as { status?: string };
  const inbox = ragInbox.get(id) ?? [];
  return status ? inbox.filter((q) => q.status === status) : inbox;
});

// the agent pushes its answer → mark answered + broadcast into every console.
app.post("/api/graphs/:id/rag-answer", async (req, reply) => {
  const { id } = req.params as { id: string };
  const b = (req.body ?? {}) as {
    id?: string;
    answer?: string;
    entities?: { id: string; name: string }[];
    paths?: string[];
    by?: string;
  };
  if (!b.id || typeof b.answer !== "string") return reply.code(400).send({ error: "rag-answer needs { id, answer }" });
  const q = (ragInbox.get(id) ?? []).find((x) => x.id === b.id);
  if (!q) return reply.code(404).send({ error: `unknown question ${b.id}` });
  q.status = "answered";
  q.answer = b.answer;

  // Merge the deterministic retrieval (precomputed at ask-time on q) with what
  // the agent highlighted: reasoning chain (paths) + entities + provenance come
  // from retrieve(); the agent only writes the prose. Union the entity sets so
  // anything Claude additionally highlighted is kept; recompute sources to match.
  const ent = new Map<string, { id: string; name: string }>();
  for (const e of q.entities ?? []) ent.set(e.id, e);   // deterministic (from /rag-questions)
  for (const e of b.entities ?? []) ent.set(e.id, e);   // + agent's
  const entities = [...ent.values()];
  const paths = (q.paths?.length ? q.paths : b.paths) ?? [];

  let sources: { id: string; documentId: string | null; text: string }[] = [];
  try {
    const state = await store.getState(id);
    const byId = new Map(state.nodes.map((n) => [n.id, n]));
    const entIds = new Set(entities.map((e) => e.id));
    const chunkIds = new Set<string>();
    for (const e of state.edges) if (e.type === "mentioned_in" && entIds.has(e.sourceId)) chunkIds.add(e.targetId);
    sources = [...chunkIds].slice(0, 8).map((cid) => {
      const c = byId.get(cid);
      const a = (c?.attributes ?? {}) as Record<string, unknown>;
      return { id: cid, documentId: (a.documentId as string) ?? c?.name ?? null, text: String(a.text ?? "").slice(0, 600) };
    }).filter((s) => s.text);
  } catch { /* graph gone / no chunks → no provenance */ }

  q.entities = entities;
  q.paths = paths;
  q.sources = sources;
  broadcast(id, { type: "rag_answer", id: q.id, answer: b.answer, entities, paths, sources, by: b.by ?? "agent:claude" });
  return q;
});

// brainstorm candidate curation actions scoped to a node set (defaults to the
// whole graph) and, unless push=false, drop them into the review queue so they
// surface in the human's Curation tab. Reuses the structural dedup heuristic.
app.post("/api/graphs/:id/agents/suggest-scoped", async (req) => {
  const { id } = req.params as { id: string };
  const b = (req.body ?? {}) as { nodeIds?: string[]; push?: boolean };
  const ids = new Set(b.nodeIds ?? []);
  const state = await store.getState(id);
  const all = dedupCandidates(state, { maxSuggestions: 200 });
  const scoped = ids.size
    ? all.filter((s) => s.targetNodeIds.length > 0 && s.targetNodeIds.every((n) => ids.has(n)))
    : all;
  if (b.push !== false) {
    const room = await getRoom(id);
    for (const s of scoped) room.addSuggestion(s);
  }
  return scoped;
});

// agent proposes a suggestion (shows in the suggestion panel)
app.post("/api/graphs/:id/suggest", async (req) => {
  const { id } = req.params as { id: string };
  const b = req.body as {
    agent?: string;
    action: "merge" | "split" | "retype" | "move" | "delete" | "edit_relation";
    targetNodeIds?: string[];
    payload?: Record<string, unknown>;
    rationale?: string;
    confidence?: number;
  };
  const room = await getRoom(id);
  const s = {
    id: crypto.randomUUID(),
    graphId: id,
    agent: b.agent ?? "agent:claude",
    action: b.action,
    targetNodeIds: b.targetNodeIds ?? [],
    targetEdgeIds: [],
    payload: b.payload ?? {},
    confidence: b.confidence ?? 0.7,
    rationale: b.rationale ?? "",
    evidence: [],
    status: "pending" as const,
    createdAt: new Date().toISOString(),
  };
  room.addSuggestion(s);
  return s;
});

// name search
app.get("/api/graphs/:id/search", async (req) => {
  const { id } = req.params as { id: string };
  const { q, limit } = req.query as { q?: string; limit?: string };
  const needle = (q ?? "").toLowerCase();
  const lim = limit ? Number(limit) : 20;
  const state = await store.getState(id);
  return state.nodes
    .filter((n) => n.name.toLowerCase().includes(needle))
    .slice(0, lim)
    .map((n) => ({ id: n.id, name: n.name, type: n.type, layer: n.layer, pinned: n.pinned }));
});

// full node detail assembled as FACTS (relations + attributes), each with its
// own confidence (Claude) / verification / supporting sources.
app.get("/api/graphs/:id/nodes/:nodeId", async (req, reply) => {
  const { id, nodeId } = req.params as { id: string; nodeId: string };
  const { asOf, axis } = req.query as { asOf?: string; axis?: string };
  const state = await store.getState(id);
  const node = state.nodes.find((n) => n.id === nodeId);
  if (!node) return reply.code(404).send({ error: `node ${nodeId} not found` });

  const byId = new Map(state.nodes.map((n) => [n.id, n]));
  const brief = (nid: string) => {
    const n = byId.get(nid);
    return n
      ? { id: n.id, name: n.name, layer: n.layer, type: n.type, validFrom: n.validFrom ?? null, validTo: n.validTo ?? null }
      : { id: nid, name: nid, layer: "?", type: "?", validFrom: null, validTo: null };
  };
  const chunkText = (cid: string) => {
    const c = byId.get(cid);
    const a = (c?.attributes ?? {}) as Record<string, unknown>;
    return c ? { id: c.id, documentId: (a.documentId as string) ?? null, text: (a.text as string) ?? null } : null;
  };
  const ax: "tx" | "valid" = axis === "valid" ? "valid" : "tx";
  const live = (o: typeof node | (typeof state.edges)[number]) => (asOf ? liveAt(o, asOf, ax) : true);

  // a verification is stale if the fact was edited AFTER it was verified:
  // any journal op touching this exact fact with createdAt > verified.at.
  const staleSince = (verifiedAt: string | undefined, match: (p: Record<string, unknown>) => boolean): boolean => {
    if (!verifiedAt) return false;
    return state.journal.some((e) => e.createdAt > verifiedAt && match(e.payload as Record<string, unknown>));
  };

  // node-level chunks (drill-down fallback for attribute facts)
  const nodeChunks = state.edges
    .filter((e) => e.type === "mentioned_in" && e.sourceId === nodeId)
    .map((e) => chunkText(e.targetId))
    .filter(Boolean);

  // ── relation facts (incident entity_relation / inter-layer edges) ──
  const factMeta = (node.attributes[FACTMETA_KEY] ?? {}) as Record<string, { confidence?: number; verified?: unknown }>;
  const relationFacts = state.edges
    .filter((e) => (e.sourceId === nodeId || e.targetId === nodeId) && !e.invalidation && e.type !== "mentioned_in" && live(e))
    .map((e) => {
      const srcIds = (e.attributes?.sourceChunkIds as string[]) ?? [];
      const sources = srcIds.map(chunkText).filter(Boolean);
      const nb = brief(e.sourceId === nodeId ? e.targetId : e.sourceId);
      return {
        id: e.id,
        kind: "relation" as const,
        dir: e.sourceId === nodeId ? "out" : "in",
        relation: e.relation ?? e.type,
        neighbor: nb,
        // the relationship's valid interval (edge time, else the neighbour's)
        validFrom: e.validFrom ?? nb.validFrom ?? null,
        validTo: e.validTo ?? nb.validTo ?? null,
        category: e.confidence,
        confidence: e.confidenceScore ?? null,
        verified: e.verified ?? null,
        stale: staleSince(e.verified?.at, (p) => p.edgeId === e.id),
        sources,
        sourceCount: sources.length || (e.attributes?.mentions as number) || 0,
      };
    });

  // ── attribute facts (skip internal keys) ──
  const SKIP = new Set([FACTMETA_KEY, "text", "descriptions", "sourceChunkIds"]);
  const attributeFacts = Object.entries(node.attributes)
    .filter(([k]) => !SKIP.has(k))
    .map(([k, v]) => ({
      id: `attr:${k}`,
      kind: "attribute" as const,
      key: k,
      value: v,
      validFrom: node.validFrom ?? null,
      validTo: node.validTo ?? null,
      confidence: factMeta[k]?.confidence ?? null,
      verified: factMeta[k]?.verified ?? null,
      stale: staleSince((factMeta[k]?.verified as { at?: string } | undefined)?.at, (p) => p.nodeId === node.id && p.attrKey === k),
      sources: nodeChunks,
      sourceCount: nodeChunks.length,
    }));

  return {
    node: { id: node.id, name: node.name, type: node.type, layer: node.layer, granularity: node.granularity, summary: node.summary ?? null, pinned: !!node.pinned, verified: node.verified ?? null, validFrom: node.validFrom, validTo: node.validTo, txFrom: node.txFrom, txTo: node.txTo },
    facts: [...relationFacts, ...attributeFacts],
    sources: nodeChunks,
  };
});

// full edge detail: all fields + endpoint nodes
app.get("/api/graphs/:id/edges/:edgeId", async (req, reply) => {
  const { id, edgeId } = req.params as { id: string; edgeId: string };
  const state = await store.getState(id);
  const edge = state.edges.find((e) => e.id === edgeId);
  if (!edge) return reply.code(404).send({ error: `edge ${edgeId} not found` });
  const byId = new Map(state.nodes.map((n) => [n.id, n]));
  const brief = (nid: string) => {
    const n = byId.get(nid);
    return n ? { id: n.id, name: n.name, layer: n.layer, type: n.type } : { id: nid, name: nid };
  };
  return { edge, source: brief(edge.sourceId), target: brief(edge.targetId) };
});

// Batagelj projection composition: what a derived (co_chunk / co_community)
// edge is "made of" — the shared intermediaries (quasi-variables) and each
// one's Newman contribution. Computed on the fly (derived edges aren't stored).
app.get("/api/graphs/:id/projection", async (req, reply) => {
  const { id } = req.params as { id: string };
  const { source, target, relation } = req.query as { source?: string; target?: string; relation?: string };
  if (!source || !target) return reply.code(400).send({ error: "need source & target" });
  const state = await store.getState(id);
  const byId = new Map(state.nodes.map((n) => [n.id, n]));
  const a = byId.get(source), b = byId.get(target);
  if (!a || !b) return reply.code(404).send({ error: "endpoint not found" });
  const via = relation === "co_community" ? "member_of" : "mentioned_in";
  const isEnt = (nid: string) => { const n = byId.get(nid); return !!n && n.layer !== "chunk" && n.layer !== "community"; };

  // intermediary → set of entities linked through it (for degree)
  const viaEnt = new Map<string, Set<string>>();
  const neigh = new Map<string, Set<string>>();
  for (const e of state.edges) {
    if (e.invalidation || e.type !== via) continue;
    const [ent, k] = isEnt(e.sourceId) ? [e.sourceId, e.targetId] : [e.targetId, e.sourceId];
    if (!isEnt(ent)) continue;
    (viaEnt.get(k) ?? viaEnt.set(k, new Set()).get(k)!).add(ent);
    (neigh.get(ent) ?? neigh.set(ent, new Set()).get(ent)!).add(k);
  }
  const shared = [...(neigh.get(source) ?? [])].filter((k) => neigh.get(target)?.has(k));
  const intermediaries = shared.map((k) => {
    const n = byId.get(k);
    const attr = (n?.attributes ?? {}) as Record<string, unknown>;
    const d = viaEnt.get(k)?.size ?? 0;
    return {
      id: k, kind: n?.layer ?? "?", name: n?.name ?? k,
      documentId: (attr.documentId as string) ?? null,
      text: attr.text ? String(attr.text).slice(0, 400) : null,
      degree: d, contribution: d > 1 ? 1 / (d - 1) : 1,
    };
  }).sort((x, y) => y.contribution - x.contribution);
  const weight = intermediaries.reduce((s, i) => s + i.contribution, 0);
  return {
    source: { id: a.id, name: a.name }, target: { id: b.id, name: b.name },
    relation: relation ?? "co_chunk", normalization: "newman",
    raw: intermediaries.length, weight, intermediaries: intermediaries.slice(0, 40),
  };
});

// temporal diff between two instants: which nodes were born/died in [from,to]
app.get("/api/graphs/:id/diff", async (req) => {
  const { id } = req.params as { id: string };
  const { from, to, axis } = req.query as { from?: string; to?: string; axis?: string };
  const state = await store.getState(id);
  const ax = parseAxis(axis);
  const alive = (t?: string) => new Set((t ? materializeAt(state, t, ax).nodes : state.nodes).map((n) => n.id));
  const A = alive(from);
  const B = alive(to);
  return { born: [...B].filter((x) => !A.has(x)), dead: [...A].filter((x) => !B.has(x)) };
});

// k-hop slice around seed nodes
app.get("/api/graphs/:id/slice", async (req) => {
  const { id } = req.params as { id: string };
  const { seeds, depth, asOf, axis, layers } = req.query as {
    seeds?: string; depth?: string; asOf?: string; axis?: string; layers?: string;
  };
  const seedIds = (seeds ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  const d = depth ? Number(depth) : 1;
  let state = await store.getState(id);
  if (asOf) state = materializeAt(state, asOf, parseAxis(axis));
  const layerSet = parseLayers(layers) ? new Set(parseLayers(layers)) : null;
  const adj = new Map<string, string[]>();
  for (const e of state.edges) {
    (adj.get(e.sourceId) ?? adj.set(e.sourceId, []).get(e.sourceId)!).push(e.targetId);
    (adj.get(e.targetId) ?? adj.set(e.targetId, []).get(e.targetId)!).push(e.sourceId);
  }
  const keep = new Set(seedIds);
  let frontier = [...seedIds];
  for (let i = 0; i < d; i++) {
    const next: string[] = [];
    for (const id2 of frontier)
      for (const nb of adj.get(id2) ?? []) if (!keep.has(nb)) { keep.add(nb); next.push(nb); }
    frontier = next;
  }
  const nodes = state.nodes
    .filter((n) => keep.has(n.id) && (!layerSet || layerSet.has(n.layer)))
    .map((n) => ({ id: n.id, name: n.name, type: n.type, layer: n.layer }));
  const visible = new Set(nodes.map((n) => n.id));
  const edges = state.edges
    .filter((e) => visible.has(e.sourceId) && visible.has(e.targetId) && !e.invalidation)
    .map((e) => ({ id: e.id, source: e.sourceId, target: e.targetId, relation: e.relation, confidence: e.confidence }));
  return { nodes, edges };
});

// interactive decision loop over HTTP (used by mcp-service)
app.post("/api/graphs/:id/decisions", async (req) => {
  const { id } = req.params as { id: string };
  const body = req.body as { by?: string; timeoutMs?: number; request: Parameters<Room["requestDecision"]>[1] };
  const room = await getRoom(id);
  return room.requestDecision(body.by ?? "agent:claude", body.request, body.timeoutMs);
});

app.post("/api/graphs/:id/decisions/:did/resolve", async (req, reply) => {
  const { id, did } = req.params as { id: string; did: string };
  const body = req.body as { choice: "accept" | "reject" | "edit" | "pin"; editedPayload?: Record<string, unknown>; actor?: string };
  const room = await getRoom(id);
  room.resolveDecision(body.actor ?? "user:anon", did, body.choice, body.editedPayload);
  if (body.choice === "pin") {
    const nodeIds = (body.editedPayload?.nodeIds as string[]) ?? [];
    if (nodeIds.length) await room.pin(nodeIds, true);
  }
  return reply.code(204).send();
});

// structural agents → suggestions
app.post("/api/graphs/:id/agents/:name/run", async (req, reply) => {
  const { id, name } = req.params as { id: string; name: string };
  const { type } = (req.query ?? {}) as { type?: string };
  const room = await getRoom(id);
  const state = await store.getState(id);
  let suggestions: Awaited<ReturnType<typeof llmDedup>> | null = null;
  if (name === "dedup") suggestions = dedupCandidates(state);
  else if (name === "orphans") suggestions = orphanRescuer(state);
  else if (name === "dedup-llm") {
    const llm = createLLM();
    if (!llm) return reply.code(400).send({ error: "LLM not configured (DEEPSEEK_API_KEY)" });
    suggestions = await llmDedup(state, llm, { type });
  }
  if (!suggestions) return reply.code(404).send({ error: `unknown agent ${name}` });
  for (const s of suggestions) room.addSuggestion(s);
  return suggestions;
});

// read analytics
app.get("/api/graphs/:id/analysis/god-nodes", async (req) => {
  const { id } = req.params as { id: string };
  const { topN } = req.query as { topN?: string };
  return godNodes(await store.getState(id), { topN: topN ? Number(topN) : 10 });
});

app.get("/api/graphs/:id/analysis/surprise-edges", async (req) => {
  const { id } = req.params as { id: string };
  const { topN } = req.query as { topN?: string };
  return surpriseEdges(await store.getState(id), { topN: topN ? Number(topN) : 20 });
});

// skills
app.get("/api/graphs/:id/skills", async (req) => {
  const { id } = req.params as { id: string };
  return store.listSkills(id);
});

// Suggest a curation skill per entity type (LLM): a named, type-scoped routine
// the human can run/edit. Saved so they appear in the skills list.
app.post("/api/graphs/:id/skills/suggest", async (req, reply) => {
  const { id } = req.params as { id: string };
  const llm = createLLM();
  if (!llm) return reply.code(400).send({ error: "LLM not configured (DEEPSEEK_API_KEY)" });
  const state = await store.getState(id);
  const byType = new Map<string, string[]>();
  for (const n of state.nodes) {
    if (n.layer === "chunk" || n.layer === "community") continue;
    (byType.get(n.type) ?? byType.set(n.type, []).get(n.type)!).push(n.name);
  }
  const types = [...byType.entries()].sort((a, b) => b[1].length - a[1].length).slice(0, 10);
  const existing = new Set((await store.listSkills(id)).map((s) => s.name));
  const made: { id: string; name: string }[] = [];
  await Promise.all(
    types.map(async ([type, names]) => {
      try {
        const { text } = await llm.complete(
          [
            { role: "system", content: `Propose ONE useful curation skill for entities of type ${type} in a knowledge graph. Return JSON {"name":"...","intent":"...","rule":"..."}: name short (≤4 words), intent one sentence, rule an imperative one-liner. Write in Russian. JSON only.` },
            { role: "user", content: `Sample ${type} names: ${names.slice(0, 25).join(", ")}` },
          ],
          { temperature: 0.3, maxTokens: 200, jsonObject: true },
        );
        const j = extractJson(text) as { name?: string; intent?: string; rule?: string } | null;
        if (!j?.name || existing.has(j.name)) return;
        const skill = {
          id: crypto.randomUUID(),
          name: j.name,
          intent: j.intent ?? "",
          graphId: id,
          sourceEntryIds: [],
          opSequence: [],
          opSummary: {},
          ruleCandidates: [j.rule ?? j.intent ?? j.name],
          selectedRuleIndex: 0,
          tier: "llm" as const,
          scope: { kind: "type" as const, type },
          createdAt: new Date().toISOString(),
        };
        await store.saveSkill(id, skill);
        made.push({ id: skill.id, name: `${type}: ${skill.name}` });
      } catch {
        /* skip type */
      }
    }),
  );
  return made;
});

app.post("/api/graphs/:id/skills/compile", async (req) => {
  const { id } = req.params as { id: string };
  const body = req.body as {
    name: string;
    intent?: string;
    entryIds: string[];
    scope: SkillScope;
    tier: SkillTier;
  };
  const state = await store.getState(id);
  const byId = new Map(state.journal.map((e) => [e.id, e]));
  const entries = body.entryIds.map((eid) => byId.get(eid)).filter((e): e is NonNullable<typeof e> => !!e);
  const nameById = new Map(state.nodes.map((n) => [n.id, n.name]));
  const skill = await compileSkill(
    { graphId: id, name: body.name, intent: body.intent, entries, scope: body.scope, tier: body.tier },
    { nameById },
  );
  await store.saveSkill(id, skill);
  return skill;
});

app.post("/api/graphs/:id/skills/:sid/run", async (req, reply) => {
  const { id, sid } = req.params as { id: string; sid: string };
  const body = (req.body ?? {}) as {
    scope?: SkillScope;
    actor?: string;
    confirmDestructive?: boolean;
  };
  const skill = (await store.listSkills(id)).find((s) => s.id === sid);
  if (!skill) return reply.code(404).send({ error: `skill ${sid} not found` });
  const scope = body.scope ?? skill.scope;
  const state = await store.getState(id);

  if (scope.dryRun) return dryRunSkill(skill, scope, state);

  const targets = resolveScopeNodes(scope, state.nodes).filter((n) => !n.pinned);
  if (isDestructiveRun(skill, targets.length, false) && !body.confirmDestructive) {
    return reply.code(409).send({
      error: `destructive: would touch ${targets.length} nodes with a delete op; resend confirmDestructive=true`,
      targetCount: targets.length,
    });
  }
  const plan = planSkillRun(skill, scope, state, body.actor ?? "user:skill-run");
  const room = await getRoom(id);
  let applied = 0;
  for (const entry of plan.entries) {
    await room.applyOp(entry.actor, entry.op, entry.payload);
    applied++;
  }
  return { applied, targetNodeIds: plan.targetNodeIds, skipped: plan.skipped };
});

// ── WebSocket hub ──
await app.ready();
const wss = new WebSocketServer({ server: app.server });

// keepalive: ping every 30s; a socket that misses a pong is dead (closed tab /
// dropped network that never sent a TCP close) → terminate it so its "close"
// handler fires room.leave and the avatar disappears.
const HEARTBEAT_MS = 30000;
setInterval(() => {
  for (const socket of wss.clients) {
    const s = socket as typeof socket & { isAlive?: boolean };
    if (s.isAlive === false) { socket.terminate(); continue; }
    s.isAlive = false;
    try { socket.ping(); } catch { /* already closing */ }
  }
}, HEARTBEAT_MS).unref?.();

wss.on("connection", async (socket, req) => {
  (socket as typeof socket & { isAlive?: boolean }).isAlive = true;
  socket.on("pong", () => { (socket as typeof socket & { isAlive?: boolean }).isAlive = true; });
  const url = new URL(req.url ?? "", "http://localhost");
  const m = url.pathname.match(/^\/ws\/graphs\/(.+)$/);
  if (!m) {
    socket.close(1008, "bad path");
    return;
  }
  const graphId = m[1]!;
  // NOTE: real auth (OAuth/JWT) lands with auth-service; for now the actor
  // is read from the query string.
  const actor = url.searchParams.get("actor") ?? "user:anon";
  const name = url.searchParams.get("name") ?? actor;
  const kind = actor.startsWith("agent:") ? "agent" : "human";

  let room: Room;
  try {
    room = await getRoom(graphId);
  } catch {
    socket.close(1011, "no such graph");
    return;
  }

  const client: Client = { socket, actor };
  let set = clients.get(graphId);
  if (!set) clients.set(graphId, (set = new Set()));
  set.add(client);
  room.join({ actor, name, color: colorFor(actor), kind });
  socket.send(JSON.stringify(room.snapshot()));

  socket.on("message", async (raw) => {
    let msg: ClientMessage;
    try {
      msg = JSON.parse(raw.toString()) as ClientMessage;
    } catch {
      return;
    }
    try {
      switch (msg.type) {
        case "op":
          await room.applyOp(actor, msg.op, msg.payload);
          break;
        case "presence":
          room.updatePresence(actor, msg.focusedNodeIds, msg.view);
          break;
        case "focus":
          room.focus(actor, msg.nodeIds, msg.note);
          break;
        case "suggest":
          room.addSuggestion(msg.suggestion);
          break;
        case "request_decision":
          void room.requestDecision(actor, msg, msg.timeoutMs);
          break;
        case "decision_resolve":
          room.resolveDecision(actor, msg.decisionId, msg.choice, msg.editedPayload);
          if (msg.choice === "pin") {
            const nodeIds = (msg.editedPayload?.nodeIds as string[]) ?? [];
            if (nodeIds.length) await room.pin(nodeIds, true);
          }
          break;
        case "peek_request":
          // someone wants to see this actor's worldview → ask them directly
          sendToActor(graphId, msg.target, { type: "peek_request", from: actor });
          break;
        case "peek_state":
          // the asked actor replied with their snapshot → hand it to the requester
          sendToActor(graphId, msg.to, { type: "peek_state", from: actor, snapshot: msg.snapshot });
          break;
        case "ping":
          socket.send(JSON.stringify({ type: "pong" } satisfies ServerMessage));
          break;
      }
    } catch (e) {
      socket.send(JSON.stringify({ type: "error", message: String((e as Error).message) } satisfies ServerMessage));
    }
  });

  socket.on("close", () => {
    set!.delete(client);
    room.leave(actor);
  });
});

await app.listen({ port: PORT, host: "0.0.0.0" });
// eslint-disable-next-line no-console
console.log(`graph-collab-service listening on :${PORT} (graphs: ${GRAPHS_DIR})`);
