<script setup lang="ts">
import { useI18n } from "vue-i18n";

const props = defineProps<{ suggestions: Record<string, unknown>[] }>();
const emit = defineEmits<{
  (e: "focus", nodeIds: string[]): void;
  (e: "accept", s: Record<string, unknown>): void;
  (e: "reject", s: Record<string, unknown>): void;
}>();
const { t } = useI18n();

const nodeIdsOf = (s: Record<string, unknown>) => (s.targetNodeIds as string[]) ?? [];
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
        @mouseenter="emit('focus', nodeIdsOf(s))"
        @mouseleave="emit('focus', [])"
      >
        <div class="card-head">
          <span class="tag">{{ s.action }}</span>
          <span class="muted small">{{ ((s.confidence as number) ?? 0).toFixed(2) }}</span>
        </div>
        <div class="rationale">{{ s.rationale }}</div>
        <div class="row gap">
          <button class="btn sm primary" @click="emit('accept', s)">✓ {{ t("accept") }}</button>
          <button class="btn sm" @click="emit('reject', s)">✕ {{ t("reject") }}</button>
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
}
.card-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
}
.tag {
  background: #2a3a5a;
  color: #cdd9ff;
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
