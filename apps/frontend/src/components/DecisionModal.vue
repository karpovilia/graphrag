<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";
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
function defer() {
  editing.value = false;
  emit("resolve", "defer");
}

// Esc defers (not-now) — the card is non-blocking, so the canvas stays usable.
function onKey(e: KeyboardEvent) {
  if (e.key === "Escape" && props.decision) defer();
}
onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => window.removeEventListener("keydown", onKey));
watch(() => props.decision, () => (editing.value = false));
</script>

<template>
  <transition name="slide">
    <div v-if="decision" class="decision-card" role="dialog" aria-live="polite">
      <div class="decision-head">
        <span>🤖 {{ t("decision") }} <span class="muted">{{ t("by") }} {{ decision.by }}</span></span>
        <button class="x" :title="t('defer')" @click="defer">✕</button>
      </div>
      <div class="decision-body">
        <p class="proposal">{{ decision.proposal }}</p>
        <div class="muted small">{{ decision.kind }} · {{ decision.nodeIds.length }} nodes</div>
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
        <button class="btn ghost" :title="t('deferTip')" @click="defer">🕒 {{ t("defer") }}</button>
      </div>
    </div>
  </transition>
</template>

<style scoped>
/* Non-blocking corner card — the canvas stays fully usable behind it. */
.decision-card {
  position: fixed;
  right: 16px;
  bottom: 16px;
  z-index: 2000;
  background: var(--gc-panel, #fff);
  color: var(--gc-fg, #202124);
  width: min(380px, 92vw);
  border: 1px solid var(--gc-border, #dadce0);
  border-left: 3px solid var(--gc-accent, #1a73e8);
  border-radius: 10px;
  padding: 14px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.18);
}
.decision-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  margin-bottom: 8px;
}
.x {
  border: none;
  background: transparent;
  color: var(--gc-muted, #80868b);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
}
.x:hover {
  color: var(--gc-fg, #202124);
}
.proposal {
  font-size: 14px;
  margin: 4px 0;
}
.decision-actions {
  display: flex;
  gap: 6px;
  margin-top: 12px;
  flex-wrap: wrap;
}
.btn.ghost {
  margin-left: auto;
  color: var(--gc-muted, #80868b);
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
  color: var(--gc-muted, #9aa0a6);
}
.small {
  font-size: 12px;
}
.slide-enter-active,
.slide-leave-active {
  transition: transform 0.18s ease, opacity 0.18s ease;
}
.slide-enter-from,
.slide-leave-to {
  transform: translateY(12px);
  opacity: 0;
}
</style>
