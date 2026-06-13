import Fastify from "fastify";
import cors from "@fastify/cors";
import { WebSocketServer, type WebSocket } from "ws";
import {
  compileSkill,
  dedupCandidates,
  dryRunSkill,
  godNodes,
  isDestructiveRun,
  orphanRescuer,
  planSkillRun,
  resolveScopeNodes,
  surpriseEdges,
  type JournalOp,
  type SkillScope,
  type SkillTier,
} from "@graphcraft/core";
import type { ClientMessage, ServerMessage } from "@graphcraft/shared";
import { GraphStore, ConcurrentEditError, NotFoundError } from "./store.js";
import { Room } from "./room.js";
import { renderGraph } from "./render.js";

const PORT = Number(process.env.COLLAB_PORT ?? 4001);
const GRAPHS_DIR = process.env.GRAPHS_DIR ?? "./graphs";

const store = new GraphStore(GRAPHS_DIR);

// ── room + client registry ──
interface Client {
  socket: WebSocket;
  actor: string;
}
const clients = new Map<string, Set<Client>>();
const rooms = new Map<string, Room>();

function broadcast(graphId: string, msg: ServerMessage): void {
  const set = clients.get(graphId);
  if (!set) return;
  const data = JSON.stringify(msg);
  for (const c of set) {
    if (c.socket.readyState === c.socket.OPEN) c.socket.send(data);
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

const COLORS = ["#ea4335", "#4f86f7", "#34a853", "#a142f4", "#ff7043", "#00acc1"];
const colorFor = (actor: string) => {
  let h = 0;
  for (const ch of actor) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return COLORS[h % COLORS.length]!;
};

// ── HTTP ──
const app = Fastify({ logger: false });
await app.register(cors, { origin: true, credentials: true });

app.get("/health", async () => ({ ok: true }));

app.get("/api/graphs", async () => store.listGraphs());

app.get("/api/graph/:id", async (req, reply) => {
  const { id } = req.params as { id: string };
  try {
    const [state, meta] = await Promise.all([store.getState(id), store.getMeta(id)]);
    const render = renderGraph(state, meta);
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

app.get("/api/graphs/:id/suggestions", async (req) => {
  const { id } = req.params as { id: string };
  return (await getRoom(id)).listSuggestions();
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

// command the canvas to center/highlight a slice
app.post("/api/graphs/:id/focus", async (req) => {
  const { id } = req.params as { id: string };
  const body = req.body as { nodeIds: string[]; note?: string; by?: string };
  (await getRoom(id)).focus(body.by ?? "agent:claude", body.nodeIds, body.note);
  return { ok: true };
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

// k-hop slice around seed nodes
app.get("/api/graphs/:id/slice", async (req) => {
  const { id } = req.params as { id: string };
  const { seeds, depth } = req.query as { seeds?: string; depth?: string };
  const seedIds = (seeds ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  const d = depth ? Number(depth) : 1;
  const state = await store.getState(id);
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
    .filter((n) => keep.has(n.id))
    .map((n) => ({ id: n.id, name: n.name, type: n.type, layer: n.layer }));
  const edges = state.edges
    .filter((e) => keep.has(e.sourceId) && keep.has(e.targetId) && !e.invalidation)
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
  const room = await getRoom(id);
  const state = await store.getState(id);
  const suggestions =
    name === "dedup"
      ? dedupCandidates(state)
      : name === "orphans"
        ? orphanRescuer(state)
        : null;
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

wss.on("connection", async (socket, req) => {
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
          room.updatePresence(actor, msg.focusedNodeIds);
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
