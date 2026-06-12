import type { Suggestion } from "../domain/journal.js";
import { newId, nowIso, type Id } from "../domain/types.js";
import type { GraphState } from "../engine/state.js";
import { entityNodes, nameSim, neighbourMap, sharedNeighbours } from "./util.js";

export interface DedupParams {
  threshold?: number;
  maxSuggestions?: number;
}

/** Propose MERGE suggestions for likely-duplicate entities. Score mirrors
 *  graphrag's NodeDrawer.mergeCandidates:
 *    nameSim*0.5 + sharedNeighbours/3*0.4 + sameType*0.1
 *  Keep pairs with score ≥ threshold OR ≥2 shared neighbours. Pinned nodes
 *  are excluded. Never auto-applies — emits Suggestions for review. */
export function dedupCandidates(
  state: GraphState,
  params: DedupParams = {},
): Suggestion[] {
  const threshold = params.threshold ?? 0.15;
  const cap = params.maxSuggestions ?? 50;
  const ents = entityNodes(state.nodes).filter((n) => !n.pinned);
  const nbr = neighbourMap(state);

  const scored: {
    a: Id;
    b: Id;
    aName: string;
    bName: string;
    aType: string;
    score: number;
    shared: number;
  }[] = [];

  for (let i = 0; i < ents.length; i++) {
    for (let j = i + 1; j < ents.length; j++) {
      const a = ents[i]!;
      const b = ents[j]!;
      const ns = nameSim(a.name, b.name);
      const shared = sharedNeighbours(nbr, a.id, b.id);
      const sameType = a.type === b.type ? 1 : 0;
      const score = ns * 0.5 + (Math.min(shared, 3) / 3) * 0.4 + sameType * 0.1;
      if (score >= threshold || shared >= 2) {
        // Survivor = the longer (more canonical) name.
        const [s, abs] = a.name.length >= b.name.length ? [a, b] : [b, a];
        scored.push({
          a: s.id,
          b: abs.id,
          aName: s.name,
          bName: abs.name,
          aType: s.type,
          score,
          shared,
        });
      }
    }
  }

  scored.sort((x, y) => y.score - x.score);

  const out: Suggestion[] = [];
  const usedAbsorbed = new Set<Id>();
  for (const c of scored) {
    if (out.length >= cap) break;
    // Don't propose the same node as absorbed twice in one batch.
    if (usedAbsorbed.has(c.b) || usedAbsorbed.has(c.a)) continue;
    usedAbsorbed.add(c.b);
    out.push({
      id: newId(),
      graphId: state.nodes[0]?.graphId ?? "",
      agent: "dedup",
      action: "merge",
      targetNodeIds: [c.a, c.b],
      targetEdgeIds: [],
      payload: {
        survivorId: c.a,
        absorbedIds: [c.b],
        reason: `dedup: score ${c.score.toFixed(2)}, ${c.shared} shared neighbours`,
        survivorName: c.aName,
        absorbedNames: [c.bName],
        entityType: c.aType,
      },
      confidence: Math.min(1, c.score),
      rationale: `«${c.bName}» looks like a duplicate of «${c.aName}» (score ${c.score.toFixed(2)}, ${c.shared} shared neighbours).`,
      evidence: [],
      status: "pending",
      createdAt: nowIso(),
    });
  }
  return out;
}
