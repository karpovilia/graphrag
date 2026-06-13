import { reactive, ref, shallowRef } from "vue";
import type {
  DecisionRequest,
  Participant,
  ServerMessage,
} from "@graphcraft/shared";
import { api, type RenderGraph } from "@/lib/api";

export function useRoom(graphId: string, actorName: () => string) {
  const graph = shallowRef<RenderGraph | null>(null);
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

  let socket: WebSocket | null = null;

  async function refresh() {
    graph.value = await api.getGraph(graphId);
    version.value = graph.value.version;
    journal.value = (await api.journal(graphId)) as Record<string, unknown>[];
    suggestions.value = (await api.suggestions(graphId)) as Record<string, unknown>[];
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
    const url = `${proto}://${location.host}/ws/graphs/${graphId}?actor=user:${encodeURIComponent(
      actorName(),
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
        case "focus":
          focus.nodeIds = msg.nodeIds;
          focus.note = msg.note ?? null;
          focus.by = msg.by;
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
      }
    };
  }

  async function resolveDecision(choice: string, editedPayload?: Record<string, unknown>) {
    if (!decision.value) return;
    const d = decision.value;
    await api.resolveDecision(graphId, d.decisionId, choice, `user:${actorName()}`, {
      ...(editedPayload ?? {}),
      nodeIds: d.nodeIds,
    });
    // If the human accepts an agent op, apply it on their behalf.
    if (choice === "accept" && d.op && d.payload) {
      await api.applyOp(graphId, d.op, editedPayload ?? d.payload, `user:${actorName()}`);
    }
    decision.value = null;
  }

  function clearFocus() {
    focus.nodeIds = [];
    focus.note = null;
    focus.by = null;
  }

  return {
    graph,
    version,
    participants,
    suggestions,
    journal,
    decision,
    focus,
    deltaStatus,
    connected,
    connect,
    refresh,
    resolveDecision,
    clearFocus,
    actions: {
      applyOp: (op: string, payload: Record<string, unknown>) =>
        api.applyOp(graphId, op, payload, `user:${actorName()}`),
      revert: () => api.revert(graphId, `user:${actorName()}`),
      runAgent: (name: "dedup" | "orphans") => api.runAgent(graphId, name),
      pin: (nodeIds: string[]) => api.pin(graphId, nodeIds, true),
      compileSkill: (body: Record<string, unknown>) => api.compileSkill(graphId, body),
    },
  };
}
