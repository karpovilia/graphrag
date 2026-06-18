<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps<{ suggestions: Record<string, unknown>[] }>();
const emit = defineEmits<{
  (e: "focus", nodeIds: string[]): void;
  (e: "accept", s: Record<string, unknown>): void;
  (e: "reject", s: Record<string, unknown>): void;
}>();
const { t } = useI18n();

const nodeIdsOf = (s: Record<string, unknown>) => (s.targetNodeIds as string[]) ?? [];

// hover = transient preview; CLICK pins a suggestion so its highlight survives
// when you move the mouse toward those nodes (mouseleave restores the pin, not clear).
const pinnedId = ref<string | null>(null);
const idOf = (s: Record<string, unknown>, i: number) => (s.id as string) ?? String(i);
function pinned(): string[] {
  const s = props.suggestions.find((x, i) => idOf(x, i) === pinnedId.value);
  return s ? nodeIdsOf(s) : [];
}
function togglePin(s: Record<string, unknown>, i: number) {
  const id = idOf(s, i);
  pinnedId.value = pinnedId.value === id ? null : id;
  emit("focus", pinned());
}
</script>

<template>
  <div class="panel-body">
    <div class="row gap">
      <button class="btn sm" @click="emit('focus', [])">{{ t("runDedup") }}</button>
    </div>
    <p v-if="!props.suggestions.length" class="muted small">{{ t("noSuggestions") }}</p>
    <ul class="list">
      <li
        v-for="(s, i) in props.suggestions"
        :key="(s.id as string) ?? i"
        class="card"
        :class="{ pinned: pinnedId === idOf(s, i) }"
        @mouseenter="emit('focus', nodeIdsOf(s))"
        @mouseleave="emit('focus', pinned())"
        @click="togglePin(s, i)"
      >
        <div class="card-head">
          <span class="tag">{{ s.action }}</span>
          <span class="muted small">{{ pinnedId === idOf(s, i) ? "📌 " : "" }}{{ ((s.confidence as number) ?? 0).toFixed(2) }}</span>
        </div>
        <div class="rationale">{{ s.rationale }}</div>
        <div class="row gap">
          <button class="btn sm primary" @click.stop="emit('accept', s)">✓ {{ t("accept") }}</button>
          <button class="btn sm" @click.stop="emit('reject', s)">✕ {{ t("reject") }}</button>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.list {
  list-style: none;
  padding: 0;
  margin: 8px 0 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.card {
  background: var(--gc-card, #20242c);
  border-radius: 8px;
  padding: 8px 10px;
  cursor: pointer;
  border: 1px solid transparent;
}
.card.pinned {
  border-color: var(--gc-accent);
  box-shadow: 0 0 0 1px var(--gc-accent) inset;
}
.card-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
}
.tag {
  background: var(--gc-accent-soft);
  color: var(--gc-accent);
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 11px;
}
.rationale {
  font-size: 13px;
  margin-bottom: 8px;
}
.row.gap {
  display: flex;
  gap: 6px;
}
.muted {
  color: #9aa0a6;
}
.small {
  font-size: 12px;
}
</style>
