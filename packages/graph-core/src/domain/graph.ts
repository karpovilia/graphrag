import type { Id, Provenance } from "./types.js";

/** The four canonical strata of a heterogeneous GraphRAG graph.
 *  Granularity grows chunk → topic. These are defaults, NOT a closed set:
 *  `Layer` is an open string so an agent can propose emergent strata while
 *  parsing a corpus (registered per-graph in GraphMeta.layers). */
export const CANONICAL_LAYERS = ["chunk", "entity", "community", "topic"] as const;
export type CanonicalLayer = (typeof CANONICAL_LAYERS)[number];
/** Open layer label. Canonical values are conventional, not enforced. */
export type Layer = string;
/** @deprecated alias kept for call-sites that iterate the canonical strata. */
export const LAYERS = CANONICAL_LAYERS;

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

/** A curator's confirmation that a fact is correct, anchored to the temporal
 *  view they verified it in (so a later time-travel can flag it as stale). */
export interface Verification {
  by: string;
  at: string;
  /** The instant the curator was viewing (null = live/now). */
  asOf?: string | null;
  /** Which axis the asOf refers to. */
  axis?: "tx" | "valid";
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
  /** Human verification (timeline-aware): who confirmed the fact, when, and
   *  at which point on which axis they were looking. null = unverified. */
  verified?: Verification | null;

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
  /** Claude's numeric confidence in this fact (0–1), set via set_confidence.
   *  Distinct from `confidence` (categorical extraction strength). */
  confidenceScore?: number | null;
  /** Per-fact human verification (a relation is a fact). */
  verified?: Verification | null;

  // ── bi-temporal stamps (identical semantics to Node) ──
  validFrom?: string | null;
  validTo?: string | null;
  txFrom?: string | null;
  txTo?: string | null;

  /** Why/when/by-which-event this edge died. null = live edge. */
  invalidation?: EdgeInvalidation | null;
}

/** Per-attribute fact metadata, stored on a node under attributes.__factmeta__
 *  so an attribute-claim can carry its own confidence + verification. */
export interface FactMeta {
  confidence?: number | null;
  verified?: Verification | null;
}
export const FACTMETA_KEY = "__factmeta__";

/** Per-graph metadata persisted in meta.json. */
export interface GraphMeta {
  id: Id;
  name: string;
  language: string;
  /** Owning project (corpus). Graphs are variants over a project's source. */
  projectId?: Id | null;
  /** Optimistic-lock counter; bumps on every persisted journal entry. */
  version: number;
  source?: string | null;
  createdAt: string;
  nodeCount: number;
  edgeCount: number;
  layersPresent: Layer[];
  /** Per-graph layer registry: canonical strata plus any emergent layers the
   *  builder/agent proposed. Drives granularity, colour and the UI legend.
   *  Canonical layers are implied even when absent here. */
  layers?: LayerDef[];
  /** Nodes pinned by a curator — excluded from every agent and skill.
   *  Stored here (not in the journal) since a pin is an annotation, not a
   *  graph edit; overlaid onto Node.pinned when the state is materialized. */
  pinnedNodeIds?: Id[];
  /** The setup scenario this graph was built from, with the canvas view it
   *  prefers (axis, communities, default type filter). Drives how the graph
   *  first opens. */
  scenario?: {
    id: string;
    title?: string;
    axis?: "tx" | "valid";
    communities?: boolean;
    types?: string[];
  };
}

/** A layer in the per-graph registry. */
export interface LayerDef {
  name: Layer;
  /** Ordering by abstraction (chunk≈0 … topic≈3); emergent strata pick a slot. */
  granularity: number;
  color?: string;
  description?: string;
  /** True when proposed by the builder/agent rather than a canonical stratum. */
  emergent?: boolean;
}

/** Canonical layer → default numeric granularity. */
export const LAYER_GRANULARITY: Record<CanonicalLayer, number> = {
  chunk: 0,
  entity: 1,
  community: 2,
  topic: 3,
};

const CANONICAL = new Set<string>(CANONICAL_LAYERS);

/** Granularity for any layer: registry def → canonical default → 1 (entity-
 *  level fallback for an unknown emergent stratum). */
export function granularityOf(layer: Layer, registry?: LayerDef[]): number {
  const def = registry?.find((d) => d.name === layer);
  if (def) return def.granularity;
  return (LAYER_GRANULARITY as Record<string, number>)[layer] ?? 1;
}

/** Resolve the effective layer registry: canonical defaults, overlaid with
 *  meta.layers, plus any layer present on a node but not yet declared (marked
 *  emergent). Sorted by granularity. */
export function layerRegistry(
  metaLayers: LayerDef[] | undefined,
  present: Iterable<Layer>,
): LayerDef[] {
  const byName = new Map<string, LayerDef>();
  for (const name of CANONICAL_LAYERS) {
    byName.set(name, { name, granularity: LAYER_GRANULARITY[name], emergent: false });
  }
  for (const d of metaLayers ?? []) byName.set(d.name, { ...byName.get(d.name), ...d });
  for (const name of present) {
    if (!byName.has(name)) {
      byName.set(name, { name, granularity: 1, emergent: true });
    }
  }
  return [...byName.values()].sort((a, b) => a.granularity - b.granularity);
}
