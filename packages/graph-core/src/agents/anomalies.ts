import type { Id } from "../domain/types.js";
import type { Confidence } from "../domain/graph.js";
import { communityOf, type GraphState } from "../engine/state.js";
import { degreeMap, entityNodes } from "./util.js";

export interface GodNode {
  id: Id;
  name: string;
  type: string;
  degree: number;
}

/** Top-N most-connected entities. Optionally drop hub noise above a degree
 *  percentile (graphify's `exclude_hubs`) — file-level super-hubs that
 *  dominate traversal without being interesting entities. */
export function godNodes(
  state: GraphState,
  params: { topN?: number; excludeHubsPercentile?: number } = {},
): GodNode[] {
  const topN = params.topN ?? 10;
  const deg = degreeMap(state);
  const ents = entityNodes(state.nodes).filter((n) => !n.pinned);

  let pool = ents;
  if (params.excludeHubsPercentile != null && ents.length > 1) {
    const degrees = ents
      .map((n) => deg.get(n.id) ?? 0)
      .sort((a, b) => a - b);
    const idx = Math.min(
      degrees.length - 1,
      Math.floor((params.excludeHubsPercentile / 100) * degrees.length),
    );
    const cutoff = degrees[idx]!;
    pool = ents.filter((n) => (deg.get(n.id) ?? 0) <= cutoff);
  }

  return pool
    .map((n) => ({
      id: n.id,
      name: n.name,
      type: n.type,
      degree: deg.get(n.id) ?? 0,
    }))
    .sort((a, b) => b.degree - a.degree)
    .slice(0, topN);
}

export interface SurpriseEdge {
  edgeId: Id;
  source: Id;
  target: Id;
  sourceName: string;
  targetName: string;
  relation: string | null;
  confidence: Confidence;
  fromCommunity: Id | null;
  toCommunity: Id | null;
  score: number;
}

const CONF_BONUS: Record<Confidence, number> = {
  ambiguous: 3,
  inferred: 2,
  extracted: 1,
};

const STRUCTURAL = new Set(["member_of", "mentioned_in", "summary_of"]);

/** Edges crossing community boundaries, ranked as "surprising". Score =
 *  confidence bonus (ambiguous > inferred > extracted) + cross-community
 *  bonus. Structural inter-layer edges are excluded. */
export function surpriseEdges(
  state: GraphState,
  params: { topN?: number } = {},
): SurpriseEdge[] {
  const topN = params.topN ?? 20;
  const nameById = new Map(state.nodes.map((n) => [n.id, n.name]));
  const out: SurpriseEdge[] = [];

  for (const e of state.edges) {
    if (STRUCTURAL.has(e.type)) continue;
    if (e.invalidation) continue;
    const from = communityOf(state, e.sourceId);
    const to = communityOf(state, e.targetId);
    const cross = from != null && to != null && from !== to;
    const score = CONF_BONUS[e.confidence] + (cross ? 3 : 0);
    if (!cross && e.confidence === "extracted") continue;
    out.push({
      edgeId: e.id,
      source: e.sourceId,
      target: e.targetId,
      sourceName: nameById.get(e.sourceId) ?? e.sourceId.slice(0, 8),
      targetName: nameById.get(e.targetId) ?? e.targetId.slice(0, 8),
      relation: e.relation ?? null,
      confidence: e.confidence,
      fromCommunity: from,
      toCommunity: to,
      score,
    });
  }

  return out.sort((a, b) => b.score - a.score).slice(0, topN);
}
