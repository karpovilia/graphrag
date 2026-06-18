import { reactive, ref, shallowRef } from "vue";
import type {
  DecisionRequest,
  Participant,
  ParticipantView,
  ServerMessage,
  ViewSnapshot,
} from "@graphcraft/shared";
import { api, type Bucket, type GraphView, type QuantSegment, type RenderGraph, type Timeline } from "@/lib/api";

export function useRoom(graphId: string, actorName: () => string) {
  // A stable id per browser TAB (survives reloads of this tab, differs across
  // tabs). Two tabs of the same person therefore connect as two distinct actors
  // — both show in presence and each is peekable — while still showing the same
  // friendly name. localStorage would be shared across tabs (collapsing them).
  const tabId =
    sessionStorage.getItem("gc:tab") ??
    (() => {
      const v = Math.random().toString(36).slice(2, 8);
      sessionStorage.setItem("gc:tab", v);
      return v;
    })();
  /** Unique presence/journal identity for THIS tab. */
  const selfActor = () => `user:${actorName()}#${tabId}`;

  const graph = shallowRef<RenderGraph | null>(null);
  /** Visible layers (empty = all) + time-travel instant ("live" = asOf null). */
  const view = reactive<GraphView>({ layers: [], types: [], asOf: null, axis: "tx", projections: false, from: null, to: null });
  /** Activity-heatmap buckets for the scrubber (per current axis). */
  const timeline = ref<Timeline | null>(null);
  /** Timeline quantization: global bucket + per-interval overrides. */
  const quantBucket = ref<Bucket | "auto">("auto");
  const quantSegments = ref<QuantSegment[]>([]);
  const version = ref(0);
  const participants = ref<Participant[]>([]);
  const suggestions = ref<Record<string, unknown>[]>([]);
  const journal = ref<Record<string, unknown>[]>([]);
  const decision = ref<(DecisionRequest & { by: string }) | null>(null);
  const focus = reactive<{ nodeIds: string[]; note: string | null; by: string | null }>({
    nodeIds: [],
    note: null,
    by: null,
  });
  /** transient nodeId → delta status for the cascade overlay */
  const deltaStatus = ref<Record<string, string>>({});
  const connected = ref(false);
  /** agent-proposed questions for the RAG console (newest first). */
  const suggestedQuestions = ref<{ id: string; text: string; rationale?: string; seedNodeIds?: string[]; by: string }[]>([]);
  /** a question posted to the RAG console (shows a pending turn). */
  const ragAsk = ref<{ id: string; question: string; by: string; seq: number } | null>(null);
  /** the agent's answer to a console question (fills the pending turn). */
  const ragAnswer = ref<{
    id: string;
    answer: string;
    entities?: { id: string; name: string }[];
    paths?: string[];
    sources?: { id: string; documentId: string | null; text: string }[];
    by: string;
    seq: number;
  } | null>(null);
  let ragSeq = 0;

  // "see what they see": a peer asked for my worldview / a peer's worldview arrived
  const peekRequest = ref<{ from: string; seq: number } | null>(null);
  const peekState = ref<{ from: string; snapshot: ViewSnapshot; seq: number } | null>(null);
  let peekSeq = 0;

  let socket: WebSocket | null = null;

  async function refreshGraph() {
    graph.value = await api.getGraph(graphId, view);
    version.value = graph.value.version;
  }

  async function refresh() {
    await Promise.all([refreshGraph(), refreshTimeline()]);
    journal.value = (await api.journal(graphId)) as Record<string, unknown>[];
    suggestions.value = (await api.suggestions(graphId)) as Record<string, unknown>[];
  }

  async function refreshTimeline() {
    timeline.value = await api.timeline(graphId, view.axis, quantBucket.value, quantSegments.value);
  }
  function setQuant(bucket: Bucket | "auto") { quantBucket.value = bucket; void refreshTimeline(); }
  function addQuantSegment(seg: QuantSegment) { quantSegments.value = [...quantSegments.value, seg]; void refreshTimeline(); }
  function removeQuantSegment(i: number) { quantSegments.value = quantSegments.value.filter((_, k) => k !== i); void refreshTimeline(); }

  /** Change the layer/time view and re-fetch. The heatmap only changes with
   *  the axis, so refetch it only then. */
  async function setView(patch: Partial<GraphView>) {
    const axisChanged = patch.axis !== undefined && patch.axis !== view.axis;
    // plain time-travel clears any diff-window halos
    if (patch.asOf !== undefined) deltaStatus.value = {};
    Object.assign(view, patch);
    await Promise.all([refreshGraph(), ...(axisChanged ? [refreshTimeline()] : [])]);
  }

  /** Select a time INTERVAL: show the graph at `to` and halo what was
   *  born/died across [from, to] (the §0 diff grammar). */
  async function setWindow(from: string, to: string) {
    view.asOf = to;
    await refreshGraph();
    try {
      const d = await api.diff(graphId, from, to, view.axis);
      const m: Record<string, string> = {};
      for (const id of d.dead) m[id] = "dead";
      for (const id of d.born) m[id] = "born";
      deltaStatus.value = m;
    } catch {
      /* ignore */
    }
  }

  function applyDelta(delta: { events?: { kind: string; nodeId?: string | null }[] }) {
    const map: Record<string, string> = {};
    for (const ev of delta.events ?? []) {
      if (!ev.nodeId) continue;
      map[ev.nodeId] = ev.kind.includes("removed")
        ? "dead"
        : ev.kind.includes("added")
          ? "born"
          : "changed";
    }
    deltaStatus.value = map;
    window.setTimeout(() => (deltaStatus.value = {}), 4000);
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${location.host}/ws/graphs/${graphId}?actor=${encodeURIComponent(
      selfActor(),
    )}&name=${encodeURIComponent(actorName())}`;
    socket = new WebSocket(url);
    socket.onopen = () => (connected.value = true);
    socket.onclose = () => {
      connected.value = false;
      window.setTimeout(connect, 1500);
    };
    socket.onmessage = (e) => {
      const msg = JSON.parse(e.data as string) as ServerMessage;
      switch (msg.type) {
        case "snapshot":
          version.value = msg.version;
          participants.value = msg.participants;
          suggestions.value = msg.suggestions as unknown as Record<string, unknown>[];
          // a snapshot after the first means an out-of-band change (day-2
          // ingestion) → refetch the graph + journal.
          void refresh();
          break;
        case "presence":
          participants.value = msg.participants;
          break;
        case "op_applied":
          version.value = msg.version;
          applyDelta(msg.delta);
          void refresh();
          break;
        case "suggestion_added":
          suggestions.value = [
            ...suggestions.value,
            msg.suggestion as unknown as Record<string, unknown>,
          ];
          break;
        case "questions_suggested":
          suggestedQuestions.value = msg.questions;
          break;
        case "focus":
          focus.nodeIds = msg.nodeIds;
          focus.note = msg.note ?? null;
          focus.by = msg.by;
          break;
        case "rag_ask":
          ragAsk.value = { id: msg.id, question: msg.question, by: msg.by, seq: ++ragSeq };
          break;
        case "rag_answer":
          ragAnswer.value = { id: msg.id, answer: msg.answer, entities: msg.entities, paths: msg.paths, sources: msg.sources, by: msg.by, seq: ++ragSeq };
          break;
        case "decision_request":
          decision.value = msg;
          focus.nodeIds = msg.nodeIds;
          focus.note = msg.proposal;
          focus.by = msg.by;
          break;
        case "decision_resolved":
          if (decision.value?.decisionId === msg.decisionId) decision.value = null;
          break;
        case "peek_request":
          peekRequest.value = { from: msg.from, seq: ++peekSeq };
          break;
        case "peek_state":
          peekState.value = { from: msg.from, snapshot: msg.snapshot, seq: ++peekSeq };
          break;
      }
    };
  }

  async function resolveDecision(choice: string, editedPayload?: Record<string, unknown>) {
    if (!decision.value) return;
    const d = decision.value;
    await api.resolveDecision(graphId, d.decisionId, choice, selfActor(), {
      ...(editedPayload ?? {}),
      nodeIds: d.nodeIds,
    });
    // If the human accepts an agent op, apply it on their behalf.
    if (choice === "accept" && d.op && d.payload) {
      await api.applyOp(graphId, d.op, editedPayload ?? d.payload, selfActor());
    }
    decision.value = null;
  }

  function clearFocus() {
    focus.nodeIds = [];
    focus.note = null;
    focus.by = null;
  }

  /** Broadcast what this human is currently looking at so others (the agent)
   *  can "see what you see". No-op until the socket is open. */
  function sendPresence(v: ParticipantView) {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "presence", focusedNodeIds: v.selectedNodeIds, view: v }));
    }
  }

  /** Ask a participant to send back their worldview (selection/scene/camera/layout). */
  function requestPeek(target: string) {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "peek_request", target }));
    }
  }
  /** Reply to a peek request with my current worldview. */
  function sendPeekState(to: string, snapshot: ViewSnapshot) {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "peek_state", to, snapshot }));
    }
  }

  return {
    graph,
    version,
    view,
    setView,
    setWindow,
    quantBucket,
    quantSegments,
    setQuant,
    addQuantSegment,
    removeQuantSegment,
    timeline,
    participants,
    suggestions,
    suggestedQuestions,
    journal,
    decision,
    focus,
    deltaStatus,
    connected,
    ragAsk,
    ragAnswer,
    connect,
    selfActor,
    refresh,
    resolveDecision,
    clearFocus,
    sendPresence,
    peekRequest,
    peekState,
    requestPeek,
    sendPeekState,
    actions: {
      applyOp: (op: string, payload: Record<string, unknown>) =>
        api.applyOp(graphId, op, payload, selfActor()),
      revert: () => api.revert(graphId, selfActor()),
      runAgent: (name: "dedup" | "orphans" | "dedup-llm") => api.runAgent(graphId, name),
      pin: (nodeIds: string[]) => api.pin(graphId, nodeIds, true),
      setPin: (nodeIds: string[], pinned: boolean) => api.pin(graphId, nodeIds, pinned),
      setVerified: (nodeId: string, verified: boolean) =>
        api.applyOp(graphId, "set_verified", { nodeId, verified, asOf: view.asOf, axis: view.axis }, selfActor()),
      runSkill: (skillId: string, nodeIds: string[], confirmDestructive = false) =>
        api.runSkill(graphId, skillId, nodeIds, selfActor(), confirmDestructive),
      compileSkill: (body: Record<string, unknown>) => api.compileSkill(graphId, body),
    },
  };
}
