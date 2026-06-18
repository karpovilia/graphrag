import {
  computeDelta,
  newId,
  nowIso,
  type CTDGDelta,
  type Id,
  type JournalEntry,
  type JournalOp,
  type Suggestion,
} from "@graphcraft/core";
import type {
  DecisionChoice,
  DecisionRequest,
  Participant,
  ParticipantView,
  ServerMessage,
  SuggestedQuestion,
} from "@graphcraft/shared";
import { GraphStore } from "./store.js";

export interface DecisionResult {
  choice: DecisionChoice | "timeout";
  editedPayload?: Record<string, unknown>;
  by?: string;
}

/** One live curation room (= one graph). Serializes ops in arrival order
 *  (last-write-wins, no merge), brokers the agent↔human decision loop, and
 *  tracks presence. Transport-agnostic: the server injects `broadcast`. */
export class Room {
  private version = 0;
  private participants = new Map<string, Participant>();
  /** actor → last activity (join / presence update / heartbeat) for staleness. */
  private lastSeen = new Map<string, number>();
  private pending = new Map<
    Id,
    {
      resolve: (r: DecisionResult) => void;
      timer?: ReturnType<typeof setTimeout>;
      req: DecisionRequest;
    }
  >();
  private suggestions: Suggestion[] = [];
  private queue: Promise<unknown> = Promise.resolve();

  constructor(
    public readonly id: string,
    private store: GraphStore,
    private broadcast: (m: ServerMessage) => void,
  ) {}

  async init(): Promise<void> {
    this.version = (await this.store.getMeta(this.id)).version;
  }

  get currentVersion(): number {
    return this.version;
  }

  /** Serialize all mutating work so before/after deltas + version stay
   *  consistent under concurrent participants. */
  private serial<T>(fn: () => Promise<T>): Promise<T> {
    const next = this.queue.then(fn, fn);
    this.queue = next.then(
      () => undefined,
      () => undefined,
    );
    return next;
  }

  async applyOp(
    actor: string,
    op: JournalOp,
    payload: Record<string, unknown>,
  ): Promise<{ entry: JournalEntry; delta: CTDGDelta; version: number }> {
    return this.serial(async () => {
      const before = await this.store.getState(this.id);
      const entry: JournalEntry = {
        id: newId(),
        graphId: this.id,
        op,
        payload,
        actor,
        createdAt: nowIso(),
      };
      const t0 = performance.now();
      const { current, version } = await this.store.appendEntry(
        this.id,
        entry,
        this.version,
      );
      this.version = version;
      const delta = computeDelta(before, current, entry, {
        recomputeMs: performance.now() - t0,
        variantVersionAfter: version,
      });
      this.broadcast({ type: "op_applied", entry, delta, version });
      return { entry, delta, version };
    });
  }

  async revertLast(
    actor: string,
  ): Promise<{ delta: CTDGDelta; version: number; removed: JournalEntry }> {
    return this.serial(async () => {
      const before = await this.store.getState(this.id);
      const { current, version, removed } = await this.store.revertLast(
        this.id,
        this.version,
      );
      this.version = version;
      const delta = computeDelta(before, current, null, {
        explanation: `Reverted ${removed.op} by ${actor}.`,
        variantVersionAfter: version,
      });
      this.broadcast({ type: "op_applied", entry: removed, delta, version });
      return { delta, version, removed };
    });
  }

  // ── agent → room ──

  focus(by: string, nodeIds: Id[], note?: string): void {
    this.broadcast({ type: "focus", nodeIds, note, by });
  }

  addSuggestion(s: Suggestion): void {
    this.suggestions.push(s);
    this.broadcast({ type: "suggestion_added", suggestion: s });
  }

  listSuggestions(): Suggestion[] {
    return this.suggestions;
  }

  // ── agent-proposed RAG questions (newest first, capped) ──
  private questions: SuggestedQuestion[] = [];

  addQuestions(qs: SuggestedQuestion[]): SuggestedQuestion[] {
    // keep only the freshest batch — older suggestions are noise and used to
    // pile up until they filled the whole panel
    this.questions = qs.slice(0, 6);
    this.broadcast({ type: "questions_suggested", questions: this.questions });
    return this.questions;
  }

  listQuestions(): SuggestedQuestion[] {
    return this.questions;
  }

  /** Open an interactive decision and block until a human resolves it (or
   *  it times out). The request is broadcast as a decision card. */
  requestDecision(
    by: string,
    req: DecisionRequest,
    timeoutMs = 120_000,
  ): Promise<DecisionResult> {
    this.broadcast({ type: "decision_request", by, ...req });
    return new Promise<DecisionResult>((resolve) => {
      const timer = setTimeout(() => {
        this.pending.delete(req.decisionId);
        resolve({ choice: "timeout" });
      }, timeoutMs);
      this.pending.set(req.decisionId, { resolve, timer, req });
    });
  }

  /** Map a decision op to the suggestion action it represents (for defer). */
  private decisionToSuggestion(req: DecisionRequest, by: string): Suggestion {
    const opToAction: Record<string, Suggestion["action"]> = {
      merge_nodes: "merge",
      split_node: "split",
      retype_node: "retype",
      move_to_community: "move",
      edit_edge: "edit_relation",
      delete_node: "delete",
      delete_edge: "delete",
    };
    const action =
      (req.op && opToAction[req.op]) ??
      ((["merge", "split", "retype", "move", "delete", "edit_relation"] as const).includes(
        req.kind as Suggestion["action"],
      )
        ? (req.kind as Suggestion["action"])
        : "merge");
    return {
      id: newId(),
      graphId: this.id,
      agent: by,
      action,
      targetNodeIds: req.nodeIds ?? [],
      targetEdgeIds: [],
      payload: req.payload ?? {},
      confidence: 0.6,
      rationale: `Отложено: ${req.proposal}`,
      evidence: [],
      status: "pending",
      createdAt: nowIso(),
    };
  }

  /** Settle a pending decision (a human clicked Accept/Reject/Edit/Pin). */
  resolveDecision(
    by: string,
    decisionId: Id,
    choice: DecisionChoice,
    editedPayload?: Record<string, unknown>,
  ): void {
    this.broadcast({ type: "decision_resolved", decisionId, choice, editedPayload, by });
    const p = this.pending.get(decisionId);
    if (p) {
      if (p.timer) clearTimeout(p.timer);
      this.pending.delete(decisionId);
      // "defer" = not now: persist the proposal in the suggestion queue so it
      // isn't lost, and unblock the agent with the deferred outcome.
      if (choice === "defer") this.addSuggestion(this.decisionToSuggestion(p.req, by));
      p.resolve({ choice, editedPayload, by });
    }
  }

  async pin(nodeIds: Id[], pinned: boolean): Promise<void> {
    await this.store.setPinned(this.id, nodeIds, pinned);
  }

  // ── presence ──

  join(p: Participant): void {
    this.participants.set(p.actor, p);
    this.lastSeen.set(p.actor, Date.now());
    this.emitPresence();
  }

  leave(actor: string): void {
    this.participants.delete(actor);
    this.lastSeen.delete(actor);
    this.emitPresence();
  }

  updatePresence(actor: string, focusedNodeIds?: Id[], view?: ParticipantView): void {
    const p = this.participants.get(actor);
    if (p) {
      if (focusedNodeIds !== undefined) p.focusedNodeIds = focusedNodeIds;
      if (view !== undefined) p.view = view;
      this.lastSeen.set(actor, Date.now());
      this.emitPresence();
    }
  }

  /** Drop stale participants: humans whose WS socket is gone (not in
   *  `liveHumanActors`), and agents whose heartbeat lapsed (> agentTtlMs).
   *  Returns how many were removed. */
  pruneStale(liveHumanActors: Set<string>, agentTtlMs: number): number {
    const now = Date.now();
    let removed = 0;
    for (const [actor, p] of this.participants) {
      const dead =
        p.kind === "human"
          ? !liveHumanActors.has(actor)
          : now - (this.lastSeen.get(actor) ?? 0) > agentTtlMs;
      if (dead) {
        this.participants.delete(actor);
        this.lastSeen.delete(actor);
        removed++;
      }
    }
    if (removed) this.emitPresence();
    return removed;
  }

  /** Snapshot of who's in the room and what they're looking at — read by the
   *  agent (via the hub's GET /presence) to "see what the human sees". */
  listParticipants(): Participant[] {
    return [...this.participants.values()];
  }

  // ── presence long-poll: a monotonic revision + waiters so an agent can block
  //    on the NEXT change instead of polling (sub-100ms reaction). ──
  private presenceRevN = 0;
  private presenceWaiters: Array<() => void> = [];

  get presenceRev(): number {
    return this.presenceRevN;
  }

  /** Resolve as soon as presence changes (rev bumps), or after timeoutMs. */
  waitForPresenceChange(timeoutMs: number): Promise<void> {
    return new Promise((resolve) => {
      let done = false;
      const fin = () => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        resolve();
      };
      const timer = setTimeout(fin, timeoutMs);
      this.presenceWaiters.push(fin);
    });
  }

  private emitPresence(): void {
    this.presenceRevN++;
    const waiters = this.presenceWaiters;
    this.presenceWaiters = [];
    for (const w of waiters) w();
    this.broadcast({ type: "presence", participants: [...this.participants.values()] });
  }

  snapshot(): ServerMessage {
    return {
      type: "snapshot",
      version: this.version,
      participants: [...this.participants.values()],
      suggestions: this.suggestions,
    };
  }

  /** After an out-of-band change (e.g. day-2 ingestion persisted directly to
   *  the store): refresh the version and push a snapshot so clients reload. */
  async reload(): Promise<void> {
    this.version = (await this.store.getMeta(this.id)).version;
    this.broadcast(this.snapshot());
  }

  participantCount(): number {
    return this.participants.size;
  }
}
