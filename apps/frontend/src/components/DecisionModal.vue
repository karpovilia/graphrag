<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import type { DecisionRequest } from "@graphcraft/shared";

const props = defineProps<{ decision: (DecisionRequest & { by: string }) | null }>();
const emit = defineEmits<{
  (e: "resolve", choice: string, editedPayload?: Record<string, unknown>): void;
}>();
const { t } = useI18n();

const editing = ref(false);
const editText = ref("");

function startEdit() {
  editing.value = true;
  editText.value = JSON.stringify(props.decision?.payload ?? {}, null, 2);
}
function submitEdit() {
  try {
    emit("resolve", "edit", JSON.parse(editText.value));
    editing.value = false;
  } catch {
    /* invalid json — ignore */
  }
}
</script>

<template>
  <div v-if="decision" class="decision-backdrop">
    <div class="decision-card">
      <div class="decision-head">
        🤖 {{ t("decision") }} <span class="muted">{{ t("by") }} {{ decision.by }}</span>
      </div>
      <div class="decision-body">
        <p class="proposal">{{ decision.proposal }}</p>
        <div class="muted small">
          {{ decision.kind }} · {{ decision.nodeIds.length }} nodes
        </div>
        <template v-if="editing">
          <textarea v-model="editText" class="edit-area" rows="6" />
          <div class="row">
            <button class="btn primary" @click="submitEdit">OK</button>
            <button class="btn" @click="editing = false">✕</button>
          </div>
        </template>
      </div>
      <div v-if="!editing" class="decision-actions">
        <button class="btn primary" @click="emit('resolve', 'accept')">✓ {{ t("accept") }}</button>
        <button class="btn" @click="emit('resolve', 'reject')">✕ {{ t("reject") }}</button>
        <button v-if="decision.op" class="btn" @click="startEdit">✎ {{ t("edit") }}</button>
        <button class="btn" @click="emit('resolve', 'pin')">📌 {{ t("pin") }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.decision-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
}
.decision-card {
  background: var(--gc-panel, #1b1e24);
  color: var(--gc-fg, #e8eaed);
  width: min(440px, 92vw);
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
}
.decision-head {
  font-weight: 600;
  margin-bottom: 8px;
}
.proposal {
  font-size: 15px;
  margin: 6px 0;
}
.decision-actions {
  display: flex;
  gap: 8px;
  margin-top: 14px;
  flex-wrap: wrap;
}
.edit-area {
  width: 100%;
  font-family: monospace;
  font-size: 12px;
  margin-top: 8px;
}
.row {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.muted {
  color: #9aa0a6;
}
.small {
  font-size: 12px;
}
</style>
