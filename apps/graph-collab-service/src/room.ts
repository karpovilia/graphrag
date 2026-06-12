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
  ServerMessage,
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
  private pending = new Map<
    Id,
    { resolve: (r: DecisionResult) => void; timer?: ReturnType<typeof setTimeout> }
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
      this.pending.set(req.decisionId, { resolve, timer });
    });
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
      p.resolve({ choice, editedPayload, by });
    }
  }

  async pin(nodeIds: Id[], pinned: boolean): Promise<void> {
    await this.store.setPinned(this.id, nodeIds, pinned);
  }

  // ── presence ──

  join(p: Participant): void {
    this.participants.set(p.actor, p);
    this.emitPresence();
  }

  leave(actor: string): void {
    this.participants.delete(actor);
    this.emitPresence();
  }

  updatePresence(actor: string, focusedNodeIds?: Id[]): void {
    const p = this.participants.get(actor);
    if (p) {
      p.focusedNodeIds = focusedNodeIds;
      this.emitPresence();
    }
  }

  private emitPresence(): void {
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

  participantCount(): number {
    return this.participants.size;
  }
}
