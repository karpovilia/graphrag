import type { Suggestion } from "../domain/journal.js";
import { newId, nowIso } from "../domain/types.js";
import type { GraphState } from "../engine/state.js";
import { degreeMap, entityNodes } from "./util.js";

/** Flag isolated entity nodes (degree 0) as DELETE suggestions — they
 *  carry no relations and usually signal extraction noise. Pinned nodes
 *  are excluded. Low confidence: the user decides. */
export function orphanRescuer(
  state: GraphState,
  params: { maxSuggestions?: number } = {},
): Suggestion[] {
  const cap = params.maxSuggestions ?? 50;
  const deg = degreeMap(state);
  const out: Suggestion[] = [];
  for (const n of entityNodes(state.nodes)) {
    if (n.pinned) continue;
    if ((deg.get(n.id) ?? 0) > 0) continue;
    out.push({
      id: newId(),
      graphId: n.graphId,
      agent: "orphan_rescuer",
      action: "delete",
      targetNodeIds: [n.id],
      targetEdgeIds: [],
      payload: { nodeId: n.id, reason: "orphan: no incident edges" },
      confidence: 0.3,
      rationale: `«${n.name}» has no relations — likely extraction noise.`,
      evidence: [],
      status: "pending",
      createdAt: nowIso(),
    });
    if (out.length >= cap) break;
  }
  return out;
}
