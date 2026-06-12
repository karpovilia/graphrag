import type { Node, Edge } from "./domain/graph.js";
import type { JournalEntry, JournalOp } from "./domain/journal.js";
import { newId, nowIso } from "./domain/types.js";
import type { GraphState } from "./engine/state.js";

let seq = 0;
const sid = (p: string) => `${p}-${++seq}`;

export function makeNode(p: Partial<Node> = {}): Node {
  return {
    id: p.id ?? sid("n"),
    graphId: p.graphId ?? "g",
    layer: p.layer ?? "entity",
    type: p.type ?? "PERSON",
    granularity: p.granularity ?? 1,
    name: p.name ?? "node",
    summary: p.summary ?? null,
    attributes: p.attributes ?? {},
    provenance: p.provenance ?? [],
    x: p.x ?? null,
    y: p.y ?? null,
    pinned: p.pinned ?? false,
    validFrom: p.validFrom ?? null,
    validTo: p.validTo ?? null,
    txFrom: p.txFrom ?? null,
    txTo: p.txTo ?? null,
  };
}

export function makeEdge(p: Partial<Edge> = {}): Edge {
  return {
    id: p.id ?? sid("e"),
    graphId: p.graphId ?? "g",
    type: p.type ?? "entity_relation",
    sourceId: p.sourceId ?? "",
    targetId: p.targetId ?? "",
    weight: p.weight ?? null,
    relation: p.relation ?? null,
    explanation: p.explanation ?? null,
    confidence: p.confidence ?? "extracted",
    provenance: p.provenance ?? [],
    attributes: p.attributes ?? {},
    validFrom: p.validFrom ?? null,
    validTo: p.validTo ?? null,
    txFrom: p.txFrom ?? null,
    txTo: p.txTo ?? null,
    invalidation: p.invalidation ?? null,
  };
}

export function makeState(p: Partial<GraphState> = {}): GraphState {
  return { nodes: p.nodes ?? [], edges: p.edges ?? [], journal: p.journal ?? [] };
}

export function makeEntry(
  op: JournalOp,
  payload: Record<string, unknown>,
  actor = "user:test",
  graphId = "g",
): JournalEntry {
  return { id: newId(), graphId, op, payload, actor, createdAt: nowIso() };
}
