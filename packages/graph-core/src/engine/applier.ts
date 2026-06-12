import type { Node, Edge } from "../domain/graph.js";
import { LAYER_GRANULARITY, type Layer } from "../domain/graph.js";
import type { JournalEntry } from "../domain/journal.js";
import { newId, type Id } from "../domain/types.js";
import { communityOf, type GraphState } from "./state.js";
import { parsePayload, type PayloadOf } from "./payloads.js";

/** Apply could not proceed because the entry references an object no
 *  longer in the state (e.g. edit on a deleted edge). */
export class JournalApplyError extends Error {}

export interface AffectedSet {
  nodeIds: Set<Id>;
  edgeIds: Set<Id>;
  communityIds: Set<Id>;
}

const emptyAffected = (): AffectedSet => ({
  nodeIds: new Set(),
  edgeIds: new Set(),
  communityIds: new Set(),
});

// ── public API ──

/** Return a NEW state with `entry` applied and appended to the journal.
 *  Pure: the caller's state is untouched. */
export function applyJournalOp(
  state: GraphState,
  entry: JournalEntry,
): GraphState {
  let nodes = [...state.nodes];
  let edges = [...state.edges];

  switch (entry.op) {
    case "merge_nodes": {
      const p = parsePayload("merge_nodes", entry.payload);
      [nodes, edges] = applyMerge(nodes, edges, p);
      break;
    }
    case "split_node": {
      const p = parsePayload("split_node", entry.payload);
      [nodes, edges] = applySplit(nodes, edges, p, entry);
      break;
    }
    case "retype_node": {
      const p = parsePayload("retype_node", entry.payload);
      nodes = updateNode(nodes, p.nodeId, { type: p.newType });
      break;
    }
    case "move_to_community": {
      const p = parsePayload("move_to_community", entry.payload);
      edges = applyMove(edges, p, entry);
      break;
    }
    case "edit_edge": {
      const p = parsePayload("edit_edge", entry.payload);
      edges = applyEditEdge(edges, p);
      break;
    }
    case "delete_edge": {
      const p = parsePayload("delete_edge", entry.payload);
      edges = applyDeleteEdge(edges, p, entry);
      break;
    }
    case "delete_node": {
      const p = parsePayload("delete_node", entry.payload);
      nodes = nodes.filter((n) => n.id !== p.nodeId);
      edges = edges.filter(
        (e) => e.sourceId !== p.nodeId && e.targetId !== p.nodeId,
      );
      break;
    }
    case "add_edge": {
      const p = parsePayload("add_edge", entry.payload);
      edges = [...edges, coerceEdge(p.edge, entry.graphId)];
      break;
    }
    case "set_summary": {
      const p = parsePayload("set_summary", entry.payload);
      nodes = updateNode(nodes, p.nodeId, { summary: p.summary });
      break;
    }
    case "update_node_name": {
      const p = parsePayload("update_node_name", entry.payload);
      nodes = updateNode(nodes, p.nodeId, { name: p.name });
      break;
    }
  }

  return { nodes, edges, journal: [...state.journal, entry] };
}

/** Apply entries in order. Used to materialize current state from a base
 *  state + its journal stream (and to power revert = replay-without-last). */
export function replayJournal(
  base: GraphState,
  entries: Iterable<JournalEntry>,
): GraphState {
  let state = base;
  for (const entry of entries) state = applyJournalOp(state, entry);
  return state;
}

/** Downstream impact of `entry` against the pre-apply state: which nodes
 *  need re-embedding, which edges were touched, which communities shifted. */
export function affectedSet(
  before: GraphState,
  entry: JournalEntry,
): AffectedSet {
  const out = emptyAffected();
  const addCommunity = (nid: Id) => {
    const c = communityOf(before, nid);
    if (c) out.communityIds.add(c);
  };

  switch (entry.op) {
    case "merge_nodes": {
      const p = parsePayload("merge_nodes", entry.payload);
      for (const nid of [p.survivorId, ...p.absorbedIds]) {
        out.nodeIds.add(nid);
        addCommunity(nid);
      }
      break;
    }
    case "split_node": {
      const p = parsePayload("split_node", entry.payload);
      out.nodeIds.add(p.originalId);
      for (const nid of newSplitIds(p, entry)) out.nodeIds.add(nid);
      addCommunity(p.originalId);
      break;
    }
    case "retype_node": {
      const p = parsePayload("retype_node", entry.payload);
      out.nodeIds.add(p.nodeId);
      addCommunity(p.nodeId);
      break;
    }
    case "move_to_community": {
      const p = parsePayload("move_to_community", entry.payload);
      out.nodeIds.add(p.nodeId);
      out.communityIds.add(p.toCommunityId);
      if (p.fromCommunityId) out.communityIds.add(p.fromCommunityId);
      else addCommunity(p.nodeId);
      break;
    }
    case "edit_edge":
    case "delete_edge": {
      const edgeId =
        entry.op === "edit_edge"
          ? parsePayload("edit_edge", entry.payload).edgeId
          : parsePayload("delete_edge", entry.payload).edgeId;
      out.edgeIds.add(edgeId);
      const edge = before.edges.find((e) => e.id === edgeId);
      if (edge) {
        out.nodeIds.add(edge.sourceId);
        out.nodeIds.add(edge.targetId);
        addCommunity(edge.sourceId);
        addCommunity(edge.targetId);
      }
      break;
    }
    case "delete_node": {
      const p = parsePayload("delete_node", entry.payload);
      out.nodeIds.add(p.nodeId);
      for (const e of before.edges) {
        if (e.sourceId === p.nodeId || e.targetId === p.nodeId)
          out.edgeIds.add(e.id);
      }
      addCommunity(p.nodeId);
      break;
    }
    case "add_edge": {
      const p = parsePayload("add_edge", entry.payload);
      const src = String(p.edge.sourceId ?? "");
      const tgt = String(p.edge.targetId ?? "");
      for (const nid of [src, tgt]) {
        if (nid) {
          out.nodeIds.add(nid);
          addCommunity(nid);
        }
      }
      break;
    }
    case "set_summary":
    case "update_node_name": {
      const nid = String(
        (entry.payload as Record<string, unknown>).nodeId ?? "",
      );
      if (nid) out.nodeIds.add(nid);
      break;
    }
  }
  return out;
}

// ── internals ──

const EDGE_FIELDS = new Set<string>([
  "type",
  "sourceId",
  "targetId",
  "weight",
  "relation",
  "explanation",
  "confidence",
  "provenance",
  "attributes",
  "validFrom",
  "validTo",
  "txFrom",
  "txTo",
  "invalidation",
]);

function applyMerge(
  nodes: Node[],
  edges: Edge[],
  p: PayloadOf<"merge_nodes">,
): [Node[], Edge[]] {
  const absorbed = new Set(p.absorbedIds);
  if (absorbed.has(p.survivorId))
    throw new JournalApplyError("survivor cannot be in absorbed list");

  if (p.newName != null) {
    let seen = false;
    nodes = nodes.map((n) => {
      if (n.id === p.survivorId) {
        seen = true;
        return { ...n, name: p.newName as string };
      }
      return n;
    });
    if (!seen)
      throw new JournalApplyError(
        `merge_nodes: survivor ${p.survivorId} not found`,
      );
  }

  nodes = nodes.filter((n) => !absorbed.has(n.id));
  const redirect = new Map<Id, Id>();
  for (const aid of absorbed) redirect.set(aid, p.survivorId);
  return [nodes, redirectEdges(edges, redirect)];
}

function applySplit(
  nodes: Node[],
  edges: Edge[],
  p: PayloadOf<"split_node">,
  entry: JournalEntry,
): [Node[], Edge[]] {
  nodes = nodes.filter((n) => n.id !== p.originalId);
  const newIds = newSplitIds(p, entry);
  const created = p.newNodes.map((spec, i) =>
    coerceNode({ id: newIds[i], ...spec }, entry.graphId),
  );
  nodes = [...nodes, ...created];

  if (newIds.length === 0) {
    return [
      nodes,
      edges.filter(
        (e) => e.sourceId !== p.originalId && e.targetId !== p.originalId,
      ),
    ];
  }

  const fallback = newIds[0]!;
  const out: Edge[] = [];
  for (const e of edges) {
    const touches = e.sourceId === p.originalId || e.targetId === p.originalId;
    if (!touches) {
      out.push(e);
      continue;
    }
    const target = p.edgeRedirect[e.id] ?? fallback;
    const newSrc = e.sourceId === p.originalId ? target : e.sourceId;
    const newTgt = e.targetId === p.originalId ? target : e.targetId;
    if (!newSrc || !newTgt || newSrc === newTgt) continue;
    out.push({ ...e, sourceId: newSrc, targetId: newTgt });
  }
  return [nodes, out];
}

function applyMove(
  edges: Edge[],
  p: PayloadOf<"move_to_community">,
  entry: JournalEntry,
): Edge[] {
  const out = edges.filter(
    (e) =>
      !(
        e.type === "member_of" &&
        e.sourceId === p.nodeId &&
        (p.fromCommunityId == null || e.targetId === p.fromCommunityId)
      ),
  );
  out.push({
    id: newId(),
    graphId: entry.graphId,
    type: "member_of",
    sourceId: p.nodeId,
    targetId: p.toCommunityId,
    confidence: "extracted",
    provenance: [],
    attributes: {},
  });
  return out;
}

function applyEditEdge(edges: Edge[], p: PayloadOf<"edit_edge">): Edge[] {
  const target = edges.find((e) => e.id === p.edgeId);
  if (!target) throw new JournalApplyError(`edit_edge: ${p.edgeId} not found`);
  const bad = Object.keys(p.updates).filter((k) => !EDGE_FIELDS.has(k));
  if (bad.length)
    throw new JournalApplyError(`edit_edge: unknown fields ${bad.join(", ")}`);
  return edges.map((e) =>
    e.id === p.edgeId ? ({ ...e, ...p.updates } as Edge) : e,
  );
}

function applyDeleteEdge(
  edges: Edge[],
  p: PayloadOf<"delete_edge">,
  entry: JournalEntry,
): Edge[] {
  if (p.reason == null) return edges.filter((e) => e.id !== p.edgeId);
  const at = p.supersededAt ?? entry.createdAt;
  const invalidation = {
    ingestionEventId: p.ingestionEventId ?? null,
    at,
    reason: p.reason,
    supersededByEdgeId: null,
    auto: entry.actor.startsWith("agent:"),
  };
  return edges.map((e) =>
    e.id === p.edgeId ? { ...e, txTo: at, invalidation } : e,
  );
}

function updateNode(nodes: Node[], id: Id, updates: Partial<Node>): Node[] {
  let found = false;
  const out = nodes.map((n) => {
    if (n.id === id) {
      found = true;
      return { ...n, ...updates };
    }
    return n;
  });
  if (!found) throw new JournalApplyError(`node ${id} not found`);
  return out;
}

/** Redirect edge endpoints; drop self-loops; dedup identical
 *  (src,tgt,type,relation), keeping the first. */
function redirectEdges(edges: Edge[], redirect: Map<Id, Id>): Edge[] {
  const out: Edge[] = [];
  const seen = new Set<string>();
  for (const e of edges) {
    const src = redirect.get(e.sourceId) ?? e.sourceId;
    const tgt = redirect.get(e.targetId) ?? e.targetId;
    if (src === tgt) continue;
    const key = `${src}|${tgt}|${e.type}|${e.relation ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(
      src === e.sourceId && tgt === e.targetId
        ? e
        : { ...e, sourceId: src, targetId: tgt },
    );
  }
  return out;
}

/** Stable ids for split pieces: use ids embedded in the spec when present,
 *  else mint fresh ones. (Caller passes deterministic ids via the journal
 *  payload so replay yields the same nodes.) */
function newSplitIds(p: PayloadOf<"split_node">, _entry: JournalEntry): Id[] {
  return p.newNodes.map((spec) => {
    const id = (spec as Record<string, unknown>).id;
    return typeof id === "string" && id ? id : newId();
  });
}

/** Build a full Node from a partial spec, filling sane defaults. */
export function coerceNode(spec: Record<string, unknown>, graphId: Id): Node {
  const layer = (spec.layer as Layer) ?? "entity";
  return {
    id: (spec.id as string) ?? newId(),
    graphId: (spec.graphId as string) ?? graphId,
    layer,
    type: (spec.type as string) ?? "MISC",
    granularity:
      (spec.granularity as number) ?? LAYER_GRANULARITY[layer] ?? 1,
    name: (spec.name as string) ?? "",
    summary: (spec.summary as string | null) ?? null,
    attributes: (spec.attributes as Record<string, unknown>) ?? {},
    provenance: (spec.provenance as Node["provenance"]) ?? [],
    x: (spec.x as number | null) ?? null,
    y: (spec.y as number | null) ?? null,
    pinned: (spec.pinned as boolean) ?? false,
    validFrom: (spec.validFrom as string | null) ?? null,
    validTo: (spec.validTo as string | null) ?? null,
    txFrom: (spec.txFrom as string | null) ?? null,
    txTo: (spec.txTo as string | null) ?? null,
  };
}

/** Build a full Edge from a partial spec, filling sane defaults. */
export function coerceEdge(spec: Record<string, unknown>, graphId: Id): Edge {
  return {
    id: (spec.id as string) ?? newId(),
    graphId: (spec.graphId as string) ?? graphId,
    type: (spec.type as Edge["type"]) ?? "entity_relation",
    sourceId: spec.sourceId as string,
    targetId: spec.targetId as string,
    weight: (spec.weight as number | null) ?? null,
    relation: (spec.relation as string | null) ?? null,
    explanation: (spec.explanation as string | null) ?? null,
    confidence: (spec.confidence as Edge["confidence"]) ?? "extracted",
    provenance: (spec.provenance as Edge["provenance"]) ?? [],
    attributes: (spec.attributes as Record<string, unknown>) ?? {},
    validFrom: (spec.validFrom as string | null) ?? null,
    validTo: (spec.validTo as string | null) ?? null,
    txFrom: (spec.txFrom as string | null) ?? null,
    txTo: (spec.txTo as string | null) ?? null,
    invalidation: (spec.invalidation as Edge["invalidation"]) ?? null,
  };
}
