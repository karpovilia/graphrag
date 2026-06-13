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
  "Get the k-hop subgraph around seed nodes (nodes + edges) for reasoning.",
  { graphId: z.string(), seeds: z.array(z.string()), depth: z.number().optional() },
  async ({ graphId, seeds, depth }) => {
    try {
      const q = new URLSearchParams({ seeds: seeds.join(","), depth: String(depth ?? 1) });
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
  "request_decision",
  "Focus the canvas and ask a human to decide (accept/reject/edit/pin). BLOCKS until a human acts in the UI (or timeout). Returns their choice.",
  {
    graphId: z.string(),
    kind: z.string(),
    proposal: z.string(),
    nodeIds: z.array(z.string()),
    op: z.string().optional(),
    payload: z.record(z.unknown()).optional(),
    options: z.array(z.enum(["accept", "reject", "edit", "pin"])).optional(),
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
            options: options ?? ["accept", "reject", "edit", "pin"],
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
  "Apply a curation op directly (journaled, broadcast to the room). Ops: merge_nodes, split_node, retype_node, move_to_community, edit_edge, delete_edge, delete_node, add_edge, set_summary, update_node_name.",
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
