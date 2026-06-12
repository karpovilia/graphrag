import type { Node, Edge } from "../domain/graph.js";
import type { TemporalDiff, TemporalDiffEntry } from "../domain/delta.js";
import type { Id } from "../domain/types.js";
import { communityOf, type GraphState } from "./state.js";

export type Axis = "tx" | "valid";

/** Is a node/edge live at instant t under the given axis?
 *  - tx (transaction time): cumulative; live iff txFrom<=t<txTo (open end =
 *    still current). A null txFrom means "not yet in the graph" → excluded.
 *  - valid (event time): real-world extent; null borders are open, so a
 *    timeless fact (both null) is live at every t and a point fact
 *    (validFrom==validTo) is live only at that instant. */
export function liveAt(o: Node | Edge, t: string, axis: Axis): boolean {
  const T = Date.parse(t);
  if (axis === "tx") {
    if (o.txFrom == null) return false;
    if (Date.parse(o.txFrom) > T) return false;
    if (o.txTo != null && T >= Date.parse(o.txTo)) return false;
    return true;
  }
  if (o.validFrom != null && Date.parse(o.validFrom) > T) return false;
  if (o.validTo != null && T > Date.parse(o.validTo)) return false;
  return true;
}

/** State filtered to facts live at t under axis (journal carried through). */
export function materializeAt(
  state: GraphState,
  t: string,
  axis: Axis,
): GraphState {
  return {
    nodes: state.nodes.filter((n) => liveAt(n, t, axis)),
    edges: state.edges.filter((e) => liveAt(e, t, axis)),
    journal: state.journal,
  };
}

/** Classify the change between two instants into the §0 delta grammar:
 *  born / dead / persisted / moved_community / invalidated. */
export function temporalDiff(
  state: GraphState,
  opts: { graphId: Id; axis: Axis; tA: string; tB: string },
): TemporalDiff {
  const { graphId, axis, tA, tB } = opts;
  const a = materializeAt(state, tA, axis);
  const b = materializeAt(state, tB, axis);

  const aNodes = new Map(a.nodes.map((n) => [n.id, n]));
  const bNodes = new Map(b.nodes.map((n) => [n.id, n]));
  const aEdges = new Map(a.edges.map((e) => [e.id, e]));
  const bEdges = new Map(b.edges.map((e) => [e.id, e]));

  const diff: TemporalDiff = {
    graphId,
    axis,
    tA,
    tB,
    born: [],
    dead: [],
    persisted: [],
    movedCommunity: [],
    invalidated: [],
    counts: {},
  };

  // nodes
  for (const [id] of bNodes) {
    if (!aNodes.has(id)) {
      diff.born.push({ id, kind: "node", state: "born" });
    } else {
      const ca = communityOf(a, id);
      const cb = communityOf(b, id);
      if (ca !== cb) {
        diff.movedCommunity.push({
          id,
          kind: "node",
          state: "moved_community",
          fromCommunityId: ca,
          toCommunityId: cb,
        });
      } else {
        diff.persisted.push({ id, kind: "node", state: "persisted" });
      }
    }
  }
  for (const [id] of aNodes) {
    if (!bNodes.has(id))
      diff.dead.push({ id, kind: "node", state: "dead" });
  }

  // edges
  for (const [id] of bEdges) {
    if (!aEdges.has(id))
      diff.born.push({ id, kind: "edge", state: "born" });
    else diff.persisted.push({ id, kind: "edge", state: "persisted" });
  }
  for (const [id, edge] of aEdges) {
    if (bEdges.has(id)) continue;
    const current = state.edges.find((e) => e.id === id) ?? edge;
    if (current.invalidation) {
      diff.invalidated.push({
        id,
        kind: "edge",
        state: "invalidated",
        invalidation: current.invalidation,
      });
    } else {
      diff.dead.push({ id, kind: "edge", state: "dead" });
    }
  }

  const count = (xs: TemporalDiffEntry[]) => xs.length;
  diff.counts = {
    born: count(diff.born),
    dead: count(diff.dead),
    persisted: count(diff.persisted),
    moved_community: count(diff.movedCommunity),
    invalidated: count(diff.invalidated),
  };
  return diff;
}
