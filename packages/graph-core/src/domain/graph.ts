import type { Id, Provenance } from "./types.js";

/** The four canonical strata of a heterogeneous GraphRAG graph.
 *  Granularity grows chunk → topic. */
export const LAYERS = ["chunk", "entity", "community", "topic"] as const;
export type Layer = (typeof LAYERS)[number];

/** Inter-layer edges plus a generic intra-layer relation. Specific
 *  semantic predicates (works_at, …) live on `relation` of an
 *  ENTITY_RELATION edge. */
export const EDGE_TYPES = [
  "mentioned_in",
  "member_of",
  "summary_of",
  "entity_relation",
  "backbone",
  "derived",
] as const;
export type EdgeType = (typeof EDGE_TYPES)[number];

/** graphify-style provenance strength on a relation. */
export const CONFIDENCE = ["extracted", "inferred", "ambiguous"] as const;
export type Confidence = (typeof CONFIDENCE)[number];

/** Why and when an edge was killed (bi-temporal invalidation). Attached
 *  to Edge.invalidation when an ingestion event or a curation delete with
 *  a `reason` retires an edge instead of hard-deleting it. Revert re-adds
 *  the edge and clears this, preserving the audit trail. */
export interface EdgeInvalidation {
  ingestionEventId?: Id | null;
  at: string;
  reason: string;
  supersededByEdgeId?: Id | null;
  auto: boolean;
}

export interface Node {
  id: Id;
  graphId: Id;
  layer: Layer;
  /** Free-form entity type (PERSON / ORG / …). Novel values are valid. */
  type: string;
  /** Higher = more abstract. chunk≈0, entity≈1, community≈2, topic≈3. */
  granularity: number;
  name: string;
  summary?: string | null;
  attributes: Record<string, unknown>;
  provenance: Provenance[];
  /** Cached force-layout position (the render engine needs x/y). */
  x?: number | null;
  y?: number | null;
  /** When true the node is excluded from every agent and skill (the
   *  paper's "pin after checking by eye"). */
  pinned?: boolean;

  // ── bi-temporal stamps ──
  /** event time T — when the fact became true in the world. */
  validFrom?: string | null;
  validTo?: string | null;
  /** transaction time T' — when the system learned the fact. */
  txFrom?: string | null;
  txTo?: string | null;
}

export interface Edge {
  id: Id;
  graphId: Id;
  type: EdgeType;
  sourceId: Id;
  targetId: Id;
  weight?: number | null;
  /** Textual predicate for ENTITY_RELATION edges; null for inter-layer. */
  relation?: string | null;
  explanation?: string | null;
  confidence: Confidence;
  provenance: Provenance[];
  attributes: Record<string, unknown>;

  // ── bi-temporal stamps (identical semantics to Node) ──
  validFrom?: string | null;
  validTo?: string | null;
  txFrom?: string | null;
  txTo?: string | null;

  /** Why/when/by-which-event this edge died. null = live edge. */
  invalidation?: EdgeInvalidation | null;
}

/** Per-graph metadata persisted in meta.json. */
export interface GraphMeta {
  id: Id;
  name: string;
  language: string;
  /** Optimistic-lock counter; bumps on every persisted journal entry. */
  version: number;
  source?: string | null;
  createdAt: string;
  nodeCount: number;
  edgeCount: number;
  layersPresent: Layer[];
  /** Nodes pinned by a curator — excluded from every agent and skill.
   *  Stored here (not in the journal) since a pin is an annotation, not a
   *  graph edit; overlaid onto Node.pinned when the state is materialized. */
  pinnedNodeIds?: Id[];
}

/** Layer → default numeric granularity. */
export const LAYER_GRANULARITY: Record<Layer, number> = {
  chunk: 0,
  entity: 1,
  community: 2,
  topic: 3,
};
