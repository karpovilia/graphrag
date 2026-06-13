<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps<{ journal: Record<string, unknown>[] }>();
const emit = defineEmits<{
  (e: "revert"): void;
  (e: "compile", entryIds: string[], name: string): void;
}>();
const { t } = useI18n();

const selected = ref<Set<string>>(new Set());
const skillName = ref("");

function toggle(id: string) {
  const s = new Set(selected.value);
  if (s.has(id)) s.delete(id);
  else s.add(id);
  selected.value = s;
}
function compile() {
  if (!selected.value.size || !skillName.value.trim()) return;
  emit("compile", [...selected.value], skillName.value.trim());
  selected.value = new Set();
  skillName.value = "";
}
</script>

<template>
  <div class="panel-body">
    <div class="row gap">
      <button class="btn sm" :disabled="!props.journal.length" @click="emit('revert')">
        ↺ {{ t("revert") }}
      </button>
    </div>
    <p v-if="!props.journal.length" class="muted small">{{ t("emptyJournal") }}</p>
    <ul class="list">
      <li v-for="(e, i) in [...props.journal].reverse()" :key="(e.id as string) ?? i" class="jentry">
        <label class="row gap">
          <input
            type="checkbox"
            :checked="selected.has(e.id as string)"
            @change="toggle(e.id as string)"
          />
          <span class="op">{{ e.op }}</span>
          <span class="muted small">{{ e.actor }}</span>
        </label>
      </li>
    </ul>
    <div v-if="selected.size" class="compile-bar">
      <input v-model="skillName" class="inp" :placeholder="t('skillName')" />
      <button class="btn sm primary" @click="compile">{{ t("compileSkill") }} ({{ selected.size }})</button>
    </div>
  </div>
</template>

<style scoped>
.list {
  list-style: none;
  padding: 0;
  margin: 8px 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.jentry {
  background: var(--gc-card, #20242c);
  border-radius: 6px;
  padding: 4px 8px;
}
.op {
  font-family: monospace;
  font-size: 12px;
}
.row.gap {
  display: flex;
  gap: 6px;
  align-items: center;
}
.compile-bar {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.inp {
  flex: 1;
  min-width: 0;
}
.muted {
  color: #9aa0a6;
}
.small {
  font-size: 12px;
}
</style>
