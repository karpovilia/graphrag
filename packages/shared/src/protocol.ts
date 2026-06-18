import type {
  Id,
  JournalOp,
  JournalEntry,
  CTDGDelta,
  Suggestion,
} from "@graphcraft/core";

/** Human decision on an agent proposal (the interactive loop). `defer` =
 *  "not now": unblocks the agent and drops the proposal into the suggestion
 *  queue to handle later, instead of forcing accept/reject. */
export const DECISION_CHOICES = ["accept", "reject", "edit", "pin", "defer"] as const;
export type DecisionChoice = (typeof DECISION_CHOICES)[number];

/** What a participant is currently looking at — broadcast over presence so
 *  others (especially the agent) can "see what you see": the selection, the
 *  timeline instant, the active filters, and the on-canvas visible slice. */
export interface ParticipantView {
  /** Selected nodes (single click + shift/lasso multi-select). */
  selectedNodeIds?: Id[];
  /** Selected edge, if any. */
  selectedEdgeId?: Id | null;
  /** Time-travel instant ("live" = null) and the axis it runs on. */
  asOf?: string | null;
  axis?: "tx" | "valid";
  /** Active layer / entity-type filters (empty = all). */
  layers?: string[];
  types?: string[];
  /** Ids of the nodes currently rendered on the canvas (the visible slice). */
  visibleNodeIds?: Id[];
  /** Which side panel the human has open (drives agent assistance: curation =
   *  generate suggestions, rag = propose questions). null = neither. */
  panel?: "curation" | "rag" | null;
}

export interface Participant {
  actor: string;
  name: string;
  color: string;
  kind: "human" | "agent";
  focusedNodeIds?: Id[];
  /** The participant's current viewing state (set by humans, read by agents). */
  view?: ParticipantView;
}

/** A participant's full "worldview", pulled on demand when someone clicks their
 *  avatar: selection, scene (filters/time), camera, and the exact force-layout
 *  node positions. Positions are too big to ride the throttled presence stream,
 *  so they are fetched point-to-point only when requested. */
export interface ViewSnapshot {
  selectedNodeIds: Id[];
  selectedEdgeId?: Id | null;
  asOf?: string | null;
  axis?: "tx" | "valid";
  layers?: string[];
  types?: string[];
  /** Local view toggles (not in the shared graph view): community hulls and
   *  Batagelj projection edges. Without these the adopted scene differs. */
  communities?: boolean;
  projections?: boolean;
  /** Pan/zoom: screen = k·world + (x,y). */
  camera?: { k: number; x: number; y: number } | null;
  /** Exact node coordinates keyed by node id: [x, y] in world space. */
  positions?: Record<Id, [number, number]>;
}

/** A candidate question an agent proposes the human could ask the graph
 *  (shown as clickable chips in the RAG console). */
export interface SuggestedQuestion {
  id: string;
  text: string;
  /** Why this question is interesting / what it would surface. */
  rationale?: string;
  /** Seed nodes the question is about (so clicking can focus them). */
  seedNodeIds?: Id[];
  by: string;
  createdAt: string;
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
  | { type: "presence"; cursor?: { x: number; y: number }; focusedNodeIds?: Id[]; view?: ParticipantView }
  | { type: "focus"; nodeIds: Id[]; note?: string }
  | { type: "suggest"; suggestion: Suggestion }
  | ({ type: "request_decision"; timeoutMs?: number } & DecisionRequest)
  | { type: "decision_resolve"; decisionId: Id; choice: DecisionChoice; editedPayload?: Record<string, unknown> }
  // "see what they see": ask a specific participant for their worldview, and the
  // reply carrying it back. Both relayed point-to-point by the hub.
  | { type: "peek_request"; target: string }
  | { type: "peek_state"; to: string; snapshot: ViewSnapshot }
  | { type: "ping" };

// ── server → clients ──
export type ServerMessage =
  | { type: "snapshot"; version: number; participants: Participant[]; suggestions: Suggestion[] }
  | { type: "op_applied"; entry: JournalEntry; delta: CTDGDelta; version: number }
  | { type: "op_rejected"; reason: string; version: number; clientOpId?: string }
  | { type: "presence"; participants: Participant[] }
  | { type: "focus"; nodeIds: Id[]; note?: string; by: string }
  // a human asked a question in the RAG console; the agent (Claude) answers it.
  | { type: "rag_ask"; id: string; question: string; by: string }
  | {
      type: "rag_answer";
      id: string;
      answer: string;
      entities?: { id: string; name: string }[];
      paths?: string[];
      sources?: { id: string; documentId: string | null; text: string }[];
      by: string;
    }
  | ({ type: "decision_request"; by: string } & DecisionRequest)
  | { type: "decision_resolved"; decisionId: Id; choice: DecisionChoice; editedPayload?: Record<string, unknown>; by: string }
  | { type: "suggestion_added"; suggestion: Suggestion }
  // an agent proposed candidate questions for the RAG console (newest first).
  | { type: "questions_suggested"; questions: SuggestedQuestion[] }
  // "see what they see": a peer asks for your worldview; the reply carries it.
  | { type: "peek_request"; from: string }
  | { type: "peek_state"; from: string; snapshot: ViewSnapshot }
  | { type: "error"; message: string }
  | { type: "pong" };
