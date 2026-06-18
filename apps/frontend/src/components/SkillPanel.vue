<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps<{
  count: number;
  names: string[];
  nodeIds: string[];
  skills: { id: string; name: string }[];
}>();
const emit = defineEmits<{
  (e: "run", skillId: string): void;
  (e: "clear"): void;
  (e: "focus", ids: string[]): void;
}>();
const active = ref<string | null>(null);
// click a card → focus the nodes the skill operates on (the selection); dim the
// rest. Click again (or another card) toggles.
function pick(id: string) {
  active.value = active.value === id ? null : id;
  emit("focus", active.value ? props.nodeIds : []);
}
const { t } = useI18n();

// merge is the built-in default skill, shown as the first card
const cards = computed(() => [
  { id: "merge", name: t("skillMerge"), desc: t("skillMergeDesc"), icon: "🔀", def: true },
  { id: "link", name: t("skillLink"), desc: t("skillLinkDesc"), icon: "🔗", def: true },
  ...props.skills.map((s) => ({ id: s.id, name: s.name, desc: t("skillCompiledDesc"), icon: "⚙", def: false })),
]);
</script>

<template>
  <div class="panel-body">
    <div class="sel">
      <span class="muted small">{{ t("selected", { n: count }) }}: {{ names.join(", ") }}{{ count > 4 ? "…" : "" }}</span>
      <button class="btn sm" @click="emit('clear')">{{ t("clear") }}</button>
    </div>
    <ul class="list">
      <li v-for="c in cards" :key="c.id" class="card" :class="{ def: c.def, active: active === c.id }" @click="pick(c.id)">
        <div class="card-head">
          <span class="tag">{{ c.icon }} {{ c.name }}</span>
          <span v-if="c.def" class="muted small">{{ t("default") }}</span>
        </div>
        <div class="rationale">{{ c.desc }}</div>
        <div class="row gap">
          <button class="btn sm primary" @click.stop="emit('run', c.id)">{{ t("run") }}</button>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.sel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.card {
  background: var(--gc-card, #20242c);
  border: 1px solid var(--gc-border);
  border-radius: 8px;
  padding: 8px 10px;
}
.card.def {
  border-color: var(--gc-accent);
}
.card { cursor: pointer; }
.card.active {
  border-color: var(--gc-accent);
  box-shadow: 0 0 0 2px var(--gc-accent) inset;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
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
  color: var(--gc-fg);
}
.row.gap {
  display: flex;
  gap: 6px;
}
.muted {
  color: var(--gc-muted, #9aa0a6);
}
.small {
  font-size: 12px;
}
</style>
