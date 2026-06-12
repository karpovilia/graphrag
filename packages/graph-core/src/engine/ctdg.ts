import type { Node, Edge } from "../domain/graph.js";
import type { CTDGDelta, CTDGEvent } from "../domain/delta.js";
import type { JournalEntry } from "../domain/journal.js";
import { nowIso, type Id } from "../domain/types.js";
import type { GraphState } from "./state.js";

const nodeSnap = (n: Node) => ({
  id: n.id,
  name: n.name,
  type: n.type,
  layer: n.layer,
  summary: n.summary ?? null,
});

const edgeSnap = (e: Edge) => ({
  id: e.id,
  source: e.sourceId,
  target: e.targetId,
  type: e.type,
  relation: e.relation ?? null,
  weight: e.weight ?? null,
});

function nodesDiff(
  before: Node[],
  after: Node[],
  t: string,
): [CTDGEvent[], Set<Id>] {
  const a = new Map(before.map((n) => [n.id, n]));
  const b = new Map(after.map((n) => [n.id, n]));
  const events: CTDGEvent[] = [];
  const affected = new Set<Id>();

  for (const [id, n] of b) {
    const prev = a.get(id);
    if (!prev) {
      events.push({ t, kind: "node_added", nodeId: id, after: nodeSnap(n) });
      affected.add(id);
      continue;
    }
    if (prev.type !== n.type) {
      events.push({
        t,
        kind: "node_retyped",
        nodeId: id,
        before: { type: prev.type },
        after: { type: n.type },
      });
      affected.add(id);
    }
    if (prev.name !== n.name) {
      events.push({
        t,
        kind: "node_renamed",
        nodeId: id,
        before: { name: prev.name },
        after: { name: n.name },
      });
      affected.add(id);
    }
    if ((prev.summary ?? null) !== (n.summary ?? null)) {
      events.push({
        t,
        kind: "node_summary_set",
        nodeId: id,
        before: { summary: prev.summary ?? null },
        after: { summary: n.summary ?? null },
      });
      affected.add(id);
    }
  }
  for (const [id, n] of a) {
    if (!b.has(id)) {
      events.push({ t, kind: "node_removed", nodeId: id, before: nodeSnap(n) });
      affected.add(id);
    }
  }
  return [events, affected];
}

function edgesDiff(
  before: Edge[],
  after: Edge[],
  t: string,
): [CTDGEvent[], Set<Id>] {
  const a = new Map(before.map((e) => [e.id, e]));
  const b = new Map(after.map((e) => [e.id, e]));
  const events: CTDGEvent[] = [];
  const affected = new Set<Id>();

  for (const [id, e] of b) {
    const prev = a.get(id);
    if (!prev) {
      events.push({ t, kind: "edge_added", edgeId: id, after: edgeSnap(e) });
      affected.add(id);
      continue;
    }
    if (
      prev.relation !== e.relation ||
      prev.weight !== e.weight ||
      prev.explanation !== e.explanation
    ) {
      events.push({
        t,
        kind: "edge_edited",
        edgeId: id,
        before: edgeSnap(prev),
        after: edgeSnap(e),
      });
      affected.add(id);
    }
  }
  for (const [id, e] of a) {
    if (!b.has(id)) {
      events.push({ t, kind: "edge_removed", edgeId: id, before: edgeSnap(e) });
      affected.add(id);
    }
  }
  return [events, affected];
}

/** Diff two states and package as a CTDG delta with a roll-up + NL note.
 *  `entry` is optional (null for skill-run / dry-run multi-op deltas). */
export function computeDelta(
  before: GraphState,
  after: GraphState,
  entry: JournalEntry | null,
  opts: {
    explanation?: string;
    recomputeMs?: number | null;
    variantVersionAfter?: number | null;
  } = {},
): CTDGDelta {
  const t = entry?.createdAt ?? nowIso();
  const [nodeEvents, nAffected] = nodesDiff(before.nodes, after.nodes, t);
  const [edgeEvents, eAffected] = edgesDiff(before.edges, after.edges, t);

  const kind = (k: string) =>
    nodeEvents.filter((e) => e.kind === k).length +
    edgeEvents.filter((e) => e.kind === k).length;

  return {
    op: entry?.op ?? "noop",
    journalEntryId: entry?.id ?? null,
    explanation: opts.explanation ?? "",
    events: [...nodeEvents, ...edgeEvents],
    affectedNodeIds: [...nAffected],
    affectedEdgeIds: [...eAffected],
    counts: {
      nodes_added: kind("node_added"),
      nodes_removed: kind("node_removed"),
      nodes_changed:
        kind("node_retyped") +
        kind("node_renamed") +
        kind("node_summary_set") +
        kind("node_community_moved"),
      edges_added: kind("edge_added"),
      edges_removed: kind("edge_removed"),
      edges_changed: kind("edge_edited"),
    },
    variantVersionAfter: opts.variantVersionAfter ?? null,
    recomputeMs: opts.recomputeMs ?? null,
  };
}
