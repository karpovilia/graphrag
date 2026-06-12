import type { Id, Provenance } from "./types.js";

/** Append-only curation operations on a graph. Every UI edit and every
 *  accepted suggestion lands here; replay of the journal against the base
 *  state reproduces the current state. */
export const JOURNAL_OPS = [
  "merge_nodes",
  "split_node",
  "retype_node",
  "move_to_community",
  "edit_edge",
  "delete_edge",
  "delete_node",
  "add_edge",
  "set_summary",
  "update_node_name",
] as const;
export type JournalOp = (typeof JOURNAL_OPS)[number];

export interface JournalEntry {
  id: Id;
  graphId: Id;
  op: JournalOp;
  /** Op-specific fields, validated against the matching payload schema at
   *  the application boundary (see engine/payloads.ts). */
  payload: Record<string, unknown>;
  /** "user:<email|name>" or "agent:<agent_name>". */
  actor: string;
  parentEntryId?: Id | null;
  createdAt: string;
}

/** Mutations an agent can propose (subset of JournalOp). Accepting a
 *  suggestion creates the matching JournalEntry. */
export const SUGGESTION_ACTIONS = [
  "merge",
  "split",
  "retype",
  "move",
  "delete",
  "edit_relation",
] as const;
export type SuggestionAction = (typeof SUGGESTION_ACTIONS)[number];

export const SUGGESTION_STATUS = [
  "pending",
  "accepted",
  "rejected",
  "expired",
] as const;
export type SuggestionStatus = (typeof SUGGESTION_STATUS)[number];

/** An agent proposal — never auto-applied. The user accepts to turn it
 *  into a JournalEntry. */
export interface Suggestion {
  id: Id;
  graphId: Id;
  agent: string;
  action: SuggestionAction;
  targetNodeIds: Id[];
  targetEdgeIds: Id[];
  payload: Record<string, unknown>;
  confidence: number;
  rationale: string;
  evidence: Provenance[];
  costEstimateTokens?: number | null;
  status: SuggestionStatus;
  createdAt: string;
  decidedAt?: string | null;
  resultingJournalEntryId?: Id | null;
}

/** Map a suggestion action to the journal op it materializes as. DELETE
 *  resolves by whether it targets edges or nodes (caller decides). */
export const ACTION_TO_OP: Record<
  Exclude<SuggestionAction, "delete">,
  JournalOp
> = {
  merge: "merge_nodes",
  split: "split_node",
  retype: "retype_node",
  move: "move_to_community",
  edit_relation: "edit_edge",
};
