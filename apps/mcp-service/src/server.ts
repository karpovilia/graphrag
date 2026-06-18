#!/usr/bin/env -S npx tsx
/** GraphCraft MCP server (stdio). Lets the calling Claude session curate a
 *  knowledge graph as a first-class participant in a live collab room:
 *  read a slice, focus the human's canvas, propose edits, request an
 *  interactive human decision (blocking), apply ops, compile skills.
 *
 *  Pure HTTP client to graph-collab-service (env COLLAB_HTTP_URL). */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const BASE = process.env.COLLAB_HTTP_URL ?? "http://127.0.0.1:4001";
const ACTOR = process.env.AGENT_ACTOR ?? "agent:claude";

async function api(path: string, init?: RequestInit): Promise<unknown> {
  const headers = init?.body
    ? { "content-type": "application/json", ...(init?.headers ?? {}) }
    : init?.headers;
  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  const text = await res.text();
  if (!res.ok) throw new Error(`${res.status} ${path}: ${text.slice(0, 300)}`);
  return text ? JSON.parse(text) : null;
}

const announced = new Set<string>();
async function ensurePresence(graphId: string): Promise<void> {
  if (announced.has(graphId)) return;
  try {
    await api(`/api/graphs/${graphId}/presence/agent`, {
      method: "POST",
      body: JSON.stringify({ actor: ACTOR, name: "Claude" }),
    });
    announced.add(graphId);
  } catch {
    /* hub may not be up yet; tool call will surface the real error */
  }
}

const ok = (data: unknown) => ({
  content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }],
});
const fail = (e: unknown) => ({
  content: [{ type: "text" as const, text: `ERROR: ${(e as Error).message}` }],
  isError: true,
});

const server = new McpServer({ name: "graphcraft", version: "0.1.0" });

// ── read tools ──
server.tool("list_graphs", "List available knowledge graphs.", {}, async () => {
  try {
    return ok(await api("/api/graphs"));
  } catch (e) {
    return fail(e);
  }
});

server.tool(
  "get_graph",
  "Get a graph's metadata (name, version, node/edge counts, layers).",
  { graphId: z.string() },
  async ({ graphId }) => {
    try {
      const g = (await api(`/api/graph/${graphId}`)) as { meta: unknown; version: number };
      return ok({ meta: g.meta, version: g.version });
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "search_nodes",
  "Find nodes whose name matches a query.",
  { graphId: z.string(), query: z.string(), limit: z.number().optional() },
  async ({ graphId, query, limit }) => {
    try {
      const q = new URLSearchParams({ q: query, ...(limit ? { limit: String(limit) } : {}) });
      return ok(await api(`/api/graphs/${graphId}/search?${q}`));
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "get_slice",
  "Get the k-hop subgraph around seed nodes (nodes + edges) for reasoning. " +
    "Optionally restrict to layers (chunk|entity|community|topic) and/or " +
    "time-travel with asOf (ISO instant) on axis tx (recorded) | valid (real-world).",
  {
    graphId: z.string(),
    seeds: z.array(z.string()),
    depth: z.number().optional(),
    layers: z.array(z.enum(["chunk", "entity", "community", "topic"])).optional(),
    asOf: z.string().optional(),
    axis: z.enum(["tx", "valid"]).optional(),
  },
  async ({ graphId, seeds, depth, layers, asOf, axis }) => {
    try {
      const q = new URLSearchParams({ seeds: seeds.join(","), depth: String(depth ?? 1) });
      if (layers?.length) q.set("layers", layers.join(","));
      if (asOf) q.set("asOf", asOf);
      if (axis) q.set("axis", axis);
      return ok(await api(`/api/graphs/${graphId}/slice?${q}`));
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "god_nodes",
  "Top hub entities by degree.",
  { graphId: z.string(), topN: z.number().optional() },
  async ({ graphId, topN }) => {
    try {
      return ok(await api(`/api/graphs/${graphId}/analysis/god-nodes?topN=${topN ?? 10}`));
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "surprise_edges",
  "Cross-community / high-confidence 'surprising' edges, ranked.",
  { graphId: z.string(), topN: z.number().optional() },
  async ({ graphId, topN }) => {
    try {
      return ok(await api(`/api/graphs/${graphId}/analysis/surprise-edges?topN=${topN ?? 20}`));
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "run_agent",
  "Run a structural curation agent ('dedup' or 'orphans') to populate suggestions.",
  { graphId: z.string(), agent: z.enum(["dedup", "orphans"]) },
  async ({ graphId, agent }) => {
    try {
      return ok(await api(`/api/graphs/${graphId}/agents/${agent}/run`, { method: "POST" }));
    } catch (e) {
      return fail(e);
    }
  },
);

// ── AI-led setup flow (pre-graph): you analyze the corpus, recommend a
//    scenario for how the graphrag will work, and the human confirms in the UI ──
server.tool(
  "list_projects",
  "List projects (corpora). Each owns a parsed source; graphs are variants built over it via the setup flow.",
  {},
  async () => {
    try { return ok(await api("/api/projects")); } catch (e) { return fail(e); }
  },
);

server.tool(
  "analyze_corpus",
  "Analyze a project's parsed corpus and propose graph SCENARIOS (how the graphrag will work). Returns the corpus profile (languages, time span, authors, detected entity kinds, top terms) and ranked scenarios. Run this first; then recommend a scenario via update_setup and let the human confirm. goal = what the human wants from the graph (free text). Extraction defaults to LightRAG (typed kinds; auto-falls back to the keyless heuristic if no LLM key); pass llm=false to force the fast keyless heuristic.",
  { projectId: z.string(), goal: z.string().optional(), llm: z.boolean().optional() },
  async ({ projectId, goal, llm }) => {
    try {
      return ok(await api(`/api/projects/${projectId}/setup/analyze`, { method: "POST", body: JSON.stringify({ goal, llm }) }));
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "get_setup",
  "Read the current setup session for a project (goal, profile, ranked scenarios, the human's selections, assistant notes, status).",
  { projectId: z.string() },
  async ({ projectId }) => {
    try { return ok(await api(`/api/projects/${projectId}/setup`)); } catch (e) { return fail(e); }
  },
);

server.tool(
  "update_setup",
  "Lead the setup: recommend a scenario, prefill the confirmed entity kinds / extractor / view, advance the step, and/or post an assistant note the human sees in the dock. All fields optional; the human can still override in the UI.",
  {
    projectId: z.string(),
    selectedScenarioId: z.string().optional(),
    confirmedTypes: z.array(z.string()).optional(),
    extractor: z.enum(["keyless", "lightrag"]).optional(),
    communities: z.boolean().optional(),
    axis: z.enum(["tx", "valid"]).optional(),
    graphName: z.string().optional(),
    goal: z.string().optional(),
    step: z.number().optional(),
    note: z.string().optional(),
  },
  async ({ projectId, note, ...patch }) => {
    try {
      if (note) await api(`/api/projects/${projectId}/setup/note`, { method: "POST", body: JSON.stringify({ by: ACTOR, text: note }) });
      const hasPatch = Object.values(patch).some((v) => v !== undefined);
      const session = hasPatch
        ? await api(`/api/projects/${projectId}/setup`, { method: "PATCH", body: JSON.stringify(patch) })
        : await api(`/api/projects/${projectId}/setup`);
      return ok(session);
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "build_graph",
  "Build the graph from the project's confirmed setup session (selected scenario + entity kinds + extractor). Returns the new graphId. Prefer letting the human press Build in the UI; use this only when asked to build directly.",
  { projectId: z.string() },
  async ({ projectId }) => {
    try { return ok(await api(`/api/projects/${projectId}/setup/build`, { method: "POST", body: "{}" })); } catch (e) { return fail(e); }
  },
);

// ── day-2 ingestion ──
server.tool(
  "ingest",
  "Day-2: ingest new documents into an existing graph. Reconciles against prior curation — re-seen merged aliases auto-link to their survivor, exact entities are reused, and incoming data contradicting a verified fact is flagged (not overwritten). Returns the reconciliation report.",
  {
    graphId: z.string(),
    documents: z.array(z.object({ id: z.string().optional(), uri: z.string().optional(), text: z.string() })),
    llm: z.boolean().optional(),
  },
  async ({ graphId, documents, llm }) => {
    try {
      return ok(
        await api(`/api/graphs/${graphId}/ingest`, {
          method: "POST",
          body: JSON.stringify({ documents, llm }),
        }),
      );
    } catch (e) {
      return fail(e);
    }
  },
);

// ── data model (JSON Schema) ──
server.tool(
  "get_schema",
  "Get the graph's data model (JSON-Schema-shaped: entity types → sections → fields). Stored, or derived from the data if none saved.",
  { graphId: z.string() },
  async ({ graphId }) => {
    try { return ok(await api(`/api/graphs/${graphId}/schema`)); } catch (e) { return fail(e); }
  },
);
server.tool(
  "derive_schema",
  "Re-derive the data model from the current graph (entity types, attribute fields, relation sections) and persist it.",
  { graphId: z.string() },
  async ({ graphId }) => {
    try { return ok(await api(`/api/graphs/${graphId}/schema/derive`, { method: "POST" })); } catch (e) { return fail(e); }
  },
);
server.tool(
  "update_schema",
  "Replace the graph's data-model schema (JSON-Schema-shaped). Use to extend/edit the model.",
  { graphId: z.string(), schema: z.record(z.unknown()) },
  async ({ graphId, schema }) => {
    try { return ok(await api(`/api/graphs/${graphId}/schema`, { method: "PUT", body: JSON.stringify(schema) })); } catch (e) { return fail(e); }
  },
);

// ── layers (open registry; emergent strata) ──
server.tool(
  "list_layers",
  "List the graph's layer registry (canonical + emergent strata) with live node counts and granularity.",
  { graphId: z.string() },
  async ({ graphId }) => {
    try {
      return ok(await api(`/api/graphs/${graphId}/layers`));
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "define_layer",
  "Define or update a layer in the registry (name, granularity 0=chunk…3=topic, optional color/description). Use to register an emergent stratum you discovered while reading the corpus.",
  {
    graphId: z.string(),
    name: z.string(),
    granularity: z.number(),
    color: z.string().optional(),
    description: z.string().optional(),
    emergent: z.boolean().optional(),
  },
  async ({ graphId, name, granularity, color, description, emergent }) => {
    try {
      return ok(
        await api(`/api/graphs/${graphId}/layers`, {
          method: "POST",
          body: JSON.stringify({ name, granularity, color, description, emergent: emergent ?? true }),
        }),
      );
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "set_layer",
  "Move a node into a layer (journaled set_layer op). Creates the layer implicitly if new; pair with define_layer to give it granularity/color.",
  { graphId: z.string(), nodeId: z.string(), newLayer: z.string(), granularity: z.number().optional() },
  async ({ graphId, nodeId, newLayer, granularity }) => {
    try {
      await ensurePresence(graphId);
      return ok(
        await api(`/api/graphs/${graphId}/ops`, {
          method: "POST",
          body: JSON.stringify({ op: "set_layer", payload: { nodeId, newLayer, granularity }, actor: ACTOR }),
        }),
      );
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "set_verified",
  "Mark a node as human/agent-verified (or clear it). Records who + when + the temporal view (asOf/axis) so later time-travel can flag it stale.",
  {
    graphId: z.string(),
    nodeId: z.string(),
    verified: z.boolean(),
    asOf: z.string().optional(),
    axis: z.enum(["tx", "valid"]).optional(),
  },
  async ({ graphId, nodeId, verified, asOf, axis }) => {
    try {
      await ensurePresence(graphId);
      return ok(
        await api(`/api/graphs/${graphId}/ops`, {
          method: "POST",
          body: JSON.stringify({ op: "set_verified", payload: { nodeId, verified, asOf, axis }, actor: ACTOR }),
        }),
      );
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "set_confidence",
  "Set Claude's numeric confidence (0–1) on a FACT: a relation edge (edgeId) or a node attribute (nodeId+attrKey). Facts ≥0.9 (or verified) show in the human's card.",
  {
    graphId: z.string(),
    edgeId: z.string().optional(),
    nodeId: z.string().optional(),
    attrKey: z.string().optional(),
    confidence: z.number().min(0).max(1),
  },
  async ({ graphId, edgeId, nodeId, attrKey, confidence }) => {
    try {
      await ensurePresence(graphId);
      return ok(
        await api(`/api/graphs/${graphId}/ops`, {
          method: "POST",
          body: JSON.stringify({ op: "set_confidence", payload: { edgeId, nodeId, attrKey, confidence }, actor: ACTOR }),
        }),
      );
    } catch (e) {
      return fail(e);
    }
  },
);

// ── canvas + loop ──
server.tool(
  "focus_view",
  "Command every connected human's canvas to center on and highlight these nodes.",
  { graphId: z.string(), nodeIds: z.array(z.string()), note: z.string().optional() },
  async ({ graphId, nodeIds, note }) => {
    try {
      await ensurePresence(graphId);
      await api(`/api/graphs/${graphId}/focus`, {
        method: "POST",
        body: JSON.stringify({ nodeIds, note, by: ACTOR }),
      });
      return ok({ focused: nodeIds.length });
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "propose",
  "Add a suggestion to the human's review queue (never auto-applied).",
  {
    graphId: z.string(),
    action: z.enum(["merge", "split", "retype", "move", "delete", "edit_relation"]),
    targetNodeIds: z.array(z.string()).optional(),
    payload: z.record(z.unknown()).optional(),
    rationale: z.string().optional(),
    confidence: z.number().optional(),
  },
  async ({ graphId, action, targetNodeIds, payload, rationale, confidence }) => {
    try {
      await ensurePresence(graphId);
      return ok(
        await api(`/api/graphs/${graphId}/suggest`, {
          method: "POST",
          body: JSON.stringify({ agent: ACTOR, action, targetNodeIds, payload, rationale, confidence }),
        }),
      );
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "suggest_questions",
  "Push candidate questions into the human's RAG console as clickable chips (newest on top). Use when the human has the RAG panel open: propose interesting questions the graph can answer about their current selection / view. Each question: text, optional rationale (why it's worth asking), optional seedNodeIds it concerns.",
  {
    graphId: z.string(),
    questions: z.array(
      z.object({
        text: z.string(),
        rationale: z.string().optional(),
        seedNodeIds: z.array(z.string()).optional(),
      }),
    ),
  },
  async ({ graphId, questions }) => {
    try {
      await ensurePresence(graphId);
      return ok(
        await api(`/api/graphs/${graphId}/questions`, {
          method: "POST",
          body: JSON.stringify({ by: ACTOR, questions }),
        }),
      );
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "answer_question",
  "Resolve a question the human asked in the RAG console (fills the pending turn). Use after answering from the graph or after running a find/highlight command. answer = the reply text (for a highlight command, a one-line summary of what you highlighted). entities = the nodes you used/highlighted; paths = optional reasoning paths.",
  {
    graphId: z.string(),
    questionId: z.string(),
    answer: z.string(),
    entities: z.array(z.object({ id: z.string(), name: z.string() })).optional(),
    paths: z.array(z.string()).optional(),
  },
  async ({ graphId, questionId, answer, entities, paths }) => {
    try {
      return ok(
        await api(`/api/graphs/${graphId}/rag-answer`, {
          method: "POST",
          body: JSON.stringify({ id: questionId, answer, entities, paths, by: ACTOR }),
        }),
      );
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "request_decision",
  "Focus the canvas and ask a human to decide (accept/reject/edit/pin). BLOCKS until a human acts in the UI (or timeout). Returns their choice.",
  {
    graphId: z.string(),
    kind: z.string(),
    proposal: z.string(),
    nodeIds: z.array(z.string()),
    op: z.string().optional(),
    payload: z.record(z.unknown()).optional(),
    options: z.array(z.enum(["accept", "reject", "edit", "pin", "defer"])).optional(),
    timeoutMs: z.number().optional(),
  },
  async ({ graphId, kind, proposal, nodeIds, op, payload, options, timeoutMs }) => {
    try {
      await ensurePresence(graphId);
      await api(`/api/graphs/${graphId}/focus`, {
        method: "POST",
        body: JSON.stringify({ nodeIds, note: proposal, by: ACTOR }),
      });
      const result = await api(`/api/graphs/${graphId}/decisions`, {
        method: "POST",
        body: JSON.stringify({
          by: ACTOR,
          timeoutMs: timeoutMs ?? 120000,
          request: {
            decisionId: crypto.randomUUID(),
            kind,
            proposal,
            op,
            payload,
            nodeIds,
            options: options ?? ["accept", "reject", "edit", "pin", "defer"],
          },
        }),
      });
      return ok(result);
    } catch (e) {
      return fail(e);
    }
  },
);

// ── mutate ──
server.tool(
  "apply_op",
  "Apply a curation op directly (journaled, broadcast to the room). Ops: merge_nodes, split_node, retype_node, move_to_community, edit_edge, delete_edge, delete_node, add_edge, set_summary, update_node_name, set_layer, set_verified, set_confidence, set_attribute.",
  { graphId: z.string(), op: z.string(), payload: z.record(z.unknown()) },
  async ({ graphId, op, payload }) => {
    try {
      await ensurePresence(graphId);
      return ok(
        await api(`/api/graphs/${graphId}/ops`, {
          method: "POST",
          body: JSON.stringify({ op, payload, actor: ACTOR }),
        }),
      );
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "journal",
  "Recent journal entries (the change history = skill training data).",
  { graphId: z.string(), limit: z.number().optional() },
  async ({ graphId, limit }) => {
    try {
      const j = (await api(`/api/graphs/${graphId}/journal`)) as unknown[];
      return ok(limit ? j.slice(-limit) : j);
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "get_presence",
  "WHAT THE HUMAN IS LOOKING AT RIGHT NOW. Call this FIRST — before browsing, screenshotting, or guessing — whenever the user references their screen ('what do I see', 'my canvas', 'my view', 'this selection', 'the nodes on screen', 'select all X'). The canvas view is per-client LOCAL state (Kinds/type filter, axis, timeline instant, selection) and is NOT shared through the room, so you cannot infer it from get_graph or a headless browser session — only presence carries it. Returns, per participant: actor/name/kind, selected nodes (ids + names), the timeline instant they're viewing (asOf/axis), active layer/type (Kinds) filters, and the on-canvas visible slice (count + sample names). Read it before focus_view / propose / request_decision so you act on what's actually on their screen.",
  { graphId: z.string() },
  async ({ graphId }) => {
    try {
      await ensurePresence(graphId);
      return ok(await api(`/api/graphs/${graphId}/presence`));
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "pull_rag",
  "RAG inbox: questions humans typed in the graph's RAG console for YOU (Claude) to answer — no server-side LLM is involved, you ARE the RAG engine. Returns each pending question with the asker's retrieval config (algorithm, model, and date/kinds/selection scope toggles + their current selection/view). For each: retrieve grounding from the graph (search_nodes / get_slice / god_nodes, honouring the config's scope), compose the answer, then push it back with answer_rag. Poll this on a loop for hands-free answering.",
  { graphId: z.string(), status: z.enum(["pending", "answered"]).optional() },
  async ({ graphId, status }) => {
    try {
      await ensurePresence(graphId);
      return ok(await api(`/api/graphs/${graphId}/rag-questions?status=${status ?? "pending"}`));
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "answer_rag",
  "Answer a console question pulled via pull_rag: your answer renders in the human's RAG console as the reply turn. Pass the question id, your composed answer, and optionally the entity nodes you grounded it on (id+name — they become clickable chips and highlight on the canvas) and the relation paths you traversed.",
  {
    graphId: z.string(),
    id: z.string(),
    answer: z.string(),
    entities: z.array(z.object({ id: z.string(), name: z.string() })).optional(),
    paths: z.array(z.string()).optional(),
  },
  async ({ graphId, id, answer, entities, paths }) => {
    try {
      await ensurePresence(graphId);
      return ok(
        await api(`/api/graphs/${graphId}/rag-answer`, {
          method: "POST",
          body: JSON.stringify({ id, answer, entities, paths, by: ACTOR }),
        }),
      );
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool(
  "suggest_curation",
  "Brainstorm candidate curation actions for a set of nodes and drop them into the human's Curation review queue (never auto-applied). Runs the structural dedup heuristic scoped to the nodes and returns the suggestions. If nodeIds is omitted, falls back to the human's current selection, then their on-canvas visible slice (via presence) — so call get_presence first, or pass nodeIds explicitly (e.g. a group you just focus_view'd). push=false returns candidates without queueing them.",
  { graphId: z.string(), nodeIds: z.array(z.string()).optional(), push: z.boolean().optional() },
  async ({ graphId, nodeIds, push }) => {
    try {
      await ensurePresence(graphId);
      let ids = nodeIds ?? [];
      if (!ids.length) {
        const pres = (await api(`/api/graphs/${graphId}/presence`)) as {
          participants?: { kind: string; selection?: { id: string }[]; visible?: { sample?: { id: string }[] } }[];
        };
        const human = pres.participants?.find((p) => p.kind === "human");
        ids = (human?.selection ?? []).map((n) => n.id);
        if (!ids.length) ids = (human?.visible?.sample ?? []).map((n) => n.id);
      }
      return ok(
        await api(`/api/graphs/${graphId}/agents/suggest-scoped`, {
          method: "POST",
          body: JSON.stringify({ nodeIds: ids, push: push ?? true }),
        }),
      );
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool("revert", "Undo the last journal entry.", { graphId: z.string() }, async ({ graphId }) => {
  try {
    return ok(await api(`/api/graphs/${graphId}/revert`, { method: "POST", body: JSON.stringify({ actor: ACTOR }) }));
  } catch (e) {
    return fail(e);
  }
});

// ── skills ──
server.tool(
  "compile_skill",
  "Compile a slice of journal entries into a reusable skill (tier: structural | embedding | llm).",
  {
    graphId: z.string(),
    name: z.string(),
    entryIds: z.array(z.string()),
    intent: z.string().optional(),
    tier: z.enum(["structural", "embedding", "llm"]).optional(),
    scope: z
      .object({
        kind: z.enum(["selection", "layer", "type", "graph"]),
        type: z.string().optional(),
        layer: z.string().optional(),
        nodeIds: z.array(z.string()).optional(),
      })
      .optional(),
  },
  async ({ graphId, name, entryIds, intent, tier, scope }) => {
    try {
      return ok(
        await api(`/api/graphs/${graphId}/skills/compile`, {
          method: "POST",
          body: JSON.stringify({ name, entryIds, intent, tier: tier ?? "structural", scope: scope ?? { kind: "graph" } }),
        }),
      );
    } catch (e) {
      return fail(e);
    }
  },
);

server.tool("list_skills", "List compiled skills.", { graphId: z.string() }, async ({ graphId }) => {
  try {
    return ok(await api(`/api/graphs/${graphId}/skills`));
  } catch (e) {
    return fail(e);
  }
});

server.tool(
  "run_skill",
  "Run a compiled skill. dryRun=true previews the impact (delta) without journalling.",
  {
    graphId: z.string(),
    skillId: z.string(),
    dryRun: z.boolean().optional(),
    confirmDestructive: z.boolean().optional(),
    scope: z
      .object({
        kind: z.enum(["selection", "layer", "type", "graph"]),
        type: z.string().optional(),
        layer: z.string().optional(),
        nodeIds: z.array(z.string()).optional(),
        dryRun: z.boolean().optional(),
      })
      .optional(),
  },
  async ({ graphId, skillId, dryRun, confirmDestructive, scope }) => {
    try {
      await ensurePresence(graphId);
      const body = { scope: scope ? { ...scope, dryRun: dryRun ?? scope.dryRun } : { kind: "graph", dryRun }, actor: ACTOR, confirmDestructive };
      return ok(await api(`/api/graphs/${graphId}/skills/${skillId}/run`, { method: "POST", body: JSON.stringify(body) }));
    } catch (e) {
      return fail(e);
    }
  },
);

const transport = new StdioServerTransport();
await server.connect(transport);
