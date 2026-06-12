import type {
  Id,
  JournalOp,
  JournalEntry,
  CTDGDelta,
  Suggestion,
} from "@graphcraft/core";

/** Human decision on an agent proposal (the interactive loop). */
export const DECISION_CHOICES = ["accept", "reject", "edit", "pin"] as const;
export type DecisionChoice = (typeof DECISION_CHOICES)[number];

export interface Participant {
  actor: string;
  name: string;
  color: string;
  kind: "human" | "agent";
  focusedNodeIds?: Id[];
}

export interface DecisionRequest {
  decisionId: Id;
  /** e.g. "merge" | "delete" | "retype" — what the agent wants to do. */
  kind: string;
  /** Human-readable proposal + the journal op it would become if accepted. */
  proposal: string;
  op?: JournalOp;
  payload?: Record<string, unknown>;
  nodeIds: Id[];
  options: DecisionChoice[];
}

// ── client → server ──
export type ClientMessage =
  | { type: "op"; op: JournalOp; payload: Record<string, unknown>; clientOpId?: string }
  | { type: "presence"; cursor?: { x: number; y: number }; focusedNodeIds?: Id[] }
  | { type: "focus"; nodeIds: Id[]; note?: string }
  | { type: "suggest"; suggestion: Suggestion }
  | ({ type: "request_decision"; timeoutMs?: number } & DecisionRequest)
  | { type: "decision_resolve"; decisionId: Id; choice: DecisionChoice; editedPayload?: Record<string, unknown> }
  | { type: "ping" };

// ── server → clients ──
export type ServerMessage =
  | { type: "snapshot"; version: number; participants: Participant[]; suggestions: Suggestion[] }
  | { type: "op_applied"; entry: JournalEntry; delta: CTDGDelta; version: number }
  | { type: "op_rejected"; reason: string; version: number; clientOpId?: string }
  | { type: "presence"; participants: Participant[] }
  | { type: "focus"; nodeIds: Id[]; note?: string; by: string }
  | ({ type: "decision_request"; by: string } & DecisionRequest)
  | { type: "decision_resolved"; decisionId: Id; choice: DecisionChoice; editedPayload?: Record<string, unknown>; by: string }
  | { type: "suggestion_added"; suggestion: Suggestion }
  | { type: "error"; message: string }
  | { type: "pong" };
