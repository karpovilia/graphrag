import type { Id } from "./types.js";
import type { EdgeInvalidation } from "./graph.js";

// ── §0 delta grammar (bi-temporal diff buckets) ──

export const TEMPORAL_STATES = [
  "born",
  "dead",
  "persisted",
  "moved_community",
  "invalidated",
] as const;
export type TemporalState = (typeof TEMPORAL_STATES)[number];

export interface TemporalDiffEntry {
  id: Id;
  kind: "node" | "edge";
  state: TemporalState;
  fromCommunityId?: Id | null;
  toCommunityId?: Id | null;
  invalidation?: EdgeInvalidation | null;
}

export interface TemporalDiff {
  graphId: Id;
  axis: "tx" | "valid";
  tA: string;
  tB: string;
  born: TemporalDiffEntry[];
  dead: TemporalDiffEntry[];
  persisted: TemporalDiffEntry[];
  movedCommunity: TemporalDiffEntry[];
  invalidated: TemporalDiffEntry[];
  counts: Record<string, number>;
}

// ── CTDG delta (per-element events from one curation op) ──

export const CTDG_EVENT_KINDS = [
  "node_added",
  "node_removed",
  "node_retyped",
  "node_renamed",
  "node_summary_set",
  "node_community_moved",
  "edge_added",
  "edge_removed",
  "edge_edited",
] as const;
export type CTDGEventKind = (typeof CTDG_EVENT_KINDS)[number];

export interface CTDGEvent {
  t: string;
  kind: CTDGEventKind;
  nodeId?: Id | null;
  edgeId?: Id | null;
  before?: Record<string, unknown> | null;
  after?: Record<string, unknown> | null;
}

/** The full impact of ONE curation op: per-element events + a roll-up +
 *  a natural-language explanation. Powers the UI delta overlay, agent
 *  self-narration, and skill dry-run previews. */
export interface CTDGDelta {
  op: string;
  journalEntryId?: Id | null;
  explanation: string;
  events: CTDGEvent[];
  affectedNodeIds: Id[];
  affectedEdgeIds: Id[];
  counts: Record<string, number>;
  variantVersionAfter?: number | null;
  recomputeMs?: number | null;
}
