import type { Node, Edge } from "../domain/graph.js";
import type { JournalEntry } from "../domain/journal.js";
import type { Id } from "../domain/types.js";

/** The graph as it flows through curation: nodes + edges + the journal of
 *  ops applied so far. Pure value object — appliers return a new state. */
export interface GraphState {
  nodes: Node[];
  edges: Edge[];
  journal: JournalEntry[];
}

export const emptyState = (): GraphState => ({
  nodes: [],
  edges: [],
  journal: [],
});

export const nodeIndex = (s: GraphState): Map<Id, Node> =>
  new Map(s.nodes.map((n) => [n.id, n]));

export const edgeIndex = (s: GraphState): Map<Id, Edge> =>
  new Map(s.edges.map((e) => [e.id, e]));

/** Community id a node belongs to via its MEMBER_OF edge (or null). */
export const communityOf = (s: GraphState, nodeId: Id): Id | null => {
  for (const e of s.edges) {
    if (e.type === "member_of" && e.sourceId === nodeId) return e.targetId;
  }
  return null;
};
