<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import GraphView from "@/components/GraphView.vue";
import DecisionModal from "@/components/DecisionModal.vue";
import SuggestionPanel from "@/components/SuggestionPanel.vue";
import JournalPanel from "@/components/JournalPanel.vue";
import { useRoom } from "@/composables/useRoom";

const { t, locale } = useI18n();

const graphId = new URLSearchParams(location.search).get("graph") ?? "sample";
const actorName = ref(
  localStorage.getItem("gc:actor") ?? `guest-${Math.random().toString(36).slice(2, 6)}`,
);
function saveActor() {
  localStorage.setItem("gc:actor", actorName.value);
}

const room = useRoom(graphId, () => actorName.value);
const tab = ref<"suggestions" | "journal">("suggestions");
const selectedId = ref<string | null>(null);
const hoverIds = ref<string[]>([]);

const focusIds = computed(() =>
  hoverIds.value.length ? hoverIds.value : room.focus.nodeIds,
);
const selectedNode = computed(
  () => room.graph.value?.graph.nodes.find((n) => n.id === selectedId.value) ?? null,
);

function setLocale(l: string) {
  locale.value = l;
  localStorage.setItem("gc:locale", l);
}

function opFor(s: Record<string, unknown>): [string | null, Record<string, unknown>] {
  const a = s.action as string;
  const p = (s.payload as Record<string, unknown>) ?? {};
  if (a === "merge") return ["merge_nodes", p];
  if (a === "retype") return ["retype_node", p];
  if (a === "move") return ["move_to_community", p];
  if (a === "split") return ["split_node", p];
  if (a === "edit_relation") return ["edit_edge", p];
  if (a === "delete") return [p.edgeId ? "delete_edge" : "delete_node", p];
  return [null, p];
}

async function acceptSuggestion(s: Record<string, unknown>) {
  const [op, payload] = opFor(s);
  if (op) await room.actions.applyOp(op, payload);
  room.suggestions.value = room.suggestions.value.filter((x) => x.id !== s.id);
}
function rejectSuggestion(s: Record<string, unknown>) {
  room.suggestions.value = room.suggestions.value.filter((x) => x.id !== s.id);
}
async function compileSkill(entryIds: string[], name: string) {
  await room.actions.compileSkill({ name, entryIds, tier: "structural", scope: { kind: "graph" } });
}

onMounted(async () => {
  await room.refresh();
  room.connect();
});
</script>

<template>
  <div class="layout">
    <header class="topbar">
      <strong>{{ t("app") }}</strong>
      <span class="muted">/ {{ room.graph.value?.name ?? graphId }}</span>
      <span class="badge">{{ t("version") }}{{ room.version.value }}</span>
      <span class="dot" :class="{ on: room.connected.value }" :title="t('online')" />
      <div class="spacer" />
      <div class="presence">
        <span
          v-for="p in room.participants.value"
          :key="p.actor"
          class="avatar"
          :style="{ background: p.color }"
          :title="p.actor"
        >{{ p.kind === "agent" ? "🤖" : p.name.slice(0, 1).toUpperCase() }}</span>
      </div>
      <input v-model="actorName" class="inp sm" :placeholder="t('actor')" @change="saveActor" />
      <select class="inp sm" :value="locale" @change="setLocale(($event.target as HTMLSelectElement).value)">
        <option value="en">EN</option>
        <option value="ru">RU</option>
      </select>
    </header>

    <main class="main">
      <section class="canvas-wrap">
        <GraphView
          :graph="room.graph.value"
          :focus-ids="focusIds"
          :delta-status="room.deltaStatus.value"
          @select-node="selectedId = $event"
        />
        <div v-if="room.focus.note && room.focus.by?.startsWith('agent')" class="focus-banner">
          🤖 {{ room.focus.note }}
        </div>
        <div v-if="selectedNode" class="node-bar">
          <span class="ellipsis">{{ selectedNode.name }}</span>
          <button class="btn sm" @click="room.actions.pin([selectedNode!.id])">📌 {{ t("pin") }}</button>
        </div>
      </section>

      <aside class="sidebar">
        <div class="tabs">
          <button :class="{ active: tab === 'suggestions' }" @click="tab = 'suggestions'">
            {{ t("suggestions") }} ({{ room.suggestions.value.length }})
          </button>
          <button :class="{ active: tab === 'journal' }" @click="tab = 'journal'">
            {{ t("journal") }}
          </button>
        </div>
        <div class="agent-buttons">
          <button class="btn sm" @click="room.actions.runAgent('dedup')">{{ t("runDedup") }}</button>
          <button class="btn sm" @click="room.actions.runAgent('orphans')">{{ t("runOrphans") }}</button>
        </div>
        <SuggestionPanel
          v-if="tab === 'suggestions'"
          :suggestions="room.suggestions.value"
          @focus="hoverIds = $event"
          @accept="acceptSuggestion"
          @reject="rejectSuggestion"
        />
        <JournalPanel
          v-else
          :journal="room.journal.value"
          @revert="room.actions.revert()"
          @compile="compileSkill"
        />
      </aside>
    </main>

    <DecisionModal :decision="room.decision.value" @resolve="room.resolveDecision" />
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
}
.topbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  background: var(--gc-panel, #1b1e24);
  border-bottom: 1px solid #2a2e36;
}
.spacer {
  flex: 1;
}
.badge {
  background: #2a3a5a;
  color: #cdd9ff;
  border-radius: 5px;
  padding: 1px 6px;
  font-size: 12px;
}
.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #d33;
}
.dot.on {
  background: #34a853;
}
.presence {
  display: flex;
  gap: 4px;
}
.avatar {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 12px;
  color: #fff;
}
.main {
  flex: 1;
  display: flex;
  min-height: 0;
}
.canvas-wrap {
  position: relative;
  flex: 1;
  min-width: 0;
}
.focus-banner {
  position: absolute;
  top: 12px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(26, 115, 232, 0.92);
  color: #fff;
  padding: 6px 14px;
  border-radius: 18px;
  font-size: 13px;
  max-width: 70%;
}
.node-bar {
  position: absolute;
  bottom: 12px;
  left: 12px;
  display: flex;
  gap: 8px;
  align-items: center;
  background: var(--gc-panel, #1b1e24);
  padding: 6px 10px;
  border-radius: 8px;
  max-width: 60%;
}
.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sidebar {
  width: clamp(300px, 28vw, 420px);
  border-left: 1px solid #2a2e36;
  background: var(--gc-panel, #1b1e24);
  display: flex;
  flex-direction: column;
  padding: 10px;
  overflow: auto;
}
.tabs {
  display: flex;
  gap: 6px;
}
.tabs button {
  flex: 1;
  background: #20242c;
  border: none;
  color: #cdd0d6;
  padding: 6px;
  border-radius: 6px;
  cursor: pointer;
}
.tabs button.active {
  background: #2a3a5a;
  color: #fff;
}
.agent-buttons {
  display: flex;
  gap: 6px;
  margin: 8px 0;
}
</style>
