<script setup lang="ts">
  import { nextTick, ref, useTemplateRef } from "vue";
  import { useI18n } from "vue-i18n";

  import type {
    AppliedOp,
    AssistantChatMessage,
    GraphVariant,
  } from "@/entities/api";
  import { useApi } from "@/lib/api-client";
  import ErrorBanner from "@/components/molecules/ErrorBanner/ErrorBanner.vue";

  type Props = {
    variant: GraphVariant;
    /** Currently selected node ids — passed as context so "удали эту
     * вершину" / "слей с выделенным" resolve without a search. */
    selectedNodeIds?: string[];
    actor?: string;
  };
  const props = withDefaults(defineProps<Props>(), {
    selectedNodeIds: () => [],
    actor: "user:ui",
  });
  const emit = defineEmits<{
    (e: "close"): void;
    (e: "variant-changed", variant: GraphVariant): void;
  }>();
  const { t } = useI18n();
  const api = useApi();

  type Turn = AssistantChatMessage & { applied?: AppliedOp[] };
  const turns = ref<Turn[]>([]);
  const input = ref("");
  const sending = ref(false);
  const errorRaw = ref<unknown>(null);
  const listRef = useTemplateRef<HTMLElement>("listRef");

  async function scrollDown() {
    await nextTick();
    if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight;
  }

  async function send() {
    const text = input.value.trim();
    if (!text || sending.value) return;
    sending.value = true;
    errorRaw.value = null;
    // History BEFORE this turn (role/content only — backend ignores `applied`).
    const history = turns.value.map((m) => ({ role: m.role, content: m.content }));
    turns.value.push({ role: "user", content: text });
    input.value = "";
    void scrollDown();
    try {
      const res = await api.graphs.assistant(props.variant.id, {
        message: text,
        selected_node_ids: props.selectedNodeIds,
        history,
        expected_version: props.variant.version,
        actor: props.actor,
      });
      turns.value.push({
        role: "assistant",
        content: res.message,
        applied: res.applied,
      });
      // Any successful op bumped the variant → repaint the graph.
      if (res.applied.some((a) => a.ok)) emit("variant-changed", res.variant);
      void scrollDown();
    } catch (e) {
      errorRaw.value = e;
      // Drop the optimistic user turn's "pending" feel by leaving it; the
      // banner explains the failure.
    } finally {
      sending.value = false;
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }
</script>

<template>
  <aside :class="$style.panel" data-testid="assistant-chat" aria-label="Curation assistant">
    <header :class="$style.head">
      <h3 :class="$style.title">{{ t("assistantChat.title") }}</h3>
      <button
        type="button"
        :class="$style.close"
        data-testid="assistant-close"
        :aria-label="t('assistantChat.close')"
        @click="emit('close')"
      >
        ×
      </button>
    </header>

    <div ref="listRef" :class="$style.list">
      <p v-if="!turns.length" :class="$style.hint">{{ t("assistantChat.placeholder") }}</p>
      <div
        v-for="(m, i) in turns"
        :key="i"
        :class="[$style.turn, m.role === 'user' ? $style.turn_user : $style.turn_assistant]"
      >
        <p :class="$style.bubble">{{ m.content }}</p>
        <ul v-if="m.applied && m.applied.length" :class="$style.ops">
          <li
            v-for="(op, j) in m.applied"
            :key="j"
            :class="[$style.op, op.ok ? $style.op_ok : $style.op_fail]"
            :title="op.error ?? ''"
          >
            {{ op.ok ? "✓" : "✕" }} {{ op.op }}
          </li>
        </ul>
      </div>
    </div>

    <ErrorBanner v-if="errorRaw" :error="errorRaw" />

    <form :class="$style.form" @submit.prevent="send">
      <textarea
        v-model="input"
        :class="$style.input"
        :placeholder="t('assistantChat.inputPlaceholder')"
        :disabled="sending"
        rows="2"
        data-testid="assistant-input"
        @keydown="onKeydown"
      />
      <button
        type="submit"
        :class="$style.send"
        data-testid="assistant-send"
        :disabled="sending || !input.trim()"
      >
        {{ sending ? t("assistantChat.sending") : t("assistantChat.send") }}
      </button>
    </form>
  </aside>
</template>

<style module>
  .panel {
    display: flex;
    flex-direction: column;
    width: 360px;
    max-width: 100%;
    height: 100%;
    border-left: 1px solid var(--ksd-border-color);
    background: var(--ksd-bg-color);
  }
  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--gr-space-sm);
    border-bottom: 1px solid var(--ksd-border-color);
  }
  .title {
    margin: 0;
    font-size: 0.95rem;
  }
  .close {
    border: none;
    background: transparent;
    color: var(--ksd-text-main-color);
    font-size: 1.25rem;
    line-height: 1;
    cursor: pointer;
  }
  .list {
    flex: 1;
    overflow-y: auto;
    padding: var(--gr-space-sm);
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-sm);
  }
  .hint {
    margin: 0;
    color: var(--ksd-text-secondary-color, var(--ksd-text-main-color));
    font-size: 0.85rem;
    opacity: 0.8;
  }
  .turn {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
    max-width: 92%;
  }
  .turn_user {
    align-self: flex-end;
    align-items: flex-end;
  }
  .turn_assistant {
    align-self: flex-start;
    align-items: flex-start;
  }
  .bubble {
    margin: 0;
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border-radius: var(--gr-radius-sm);
    font-size: 0.875rem;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .turn_user .bubble {
    background: var(--ksd-accent-color);
    color: #fff;
  }
  .turn_assistant .bubble {
    background: var(--ksd-bg-secondary-color, rgb(127 127 127 / 12%));
    color: var(--ksd-text-main-color);
  }
  .ops {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: var(--gr-space-2xs);
  }
  .op {
    font-size: 0.72rem;
    padding: 1px var(--gr-space-2xs);
    border-radius: var(--gr-radius-sm);
    font-family: var(--gr-font-mono, monospace);
  }
  .op_ok {
    background: rgb(40 167 69 / 18%);
    color: var(--ksd-text-main-color);
  }
  .op_fail {
    background: rgb(220 53 69 / 20%);
    color: var(--ksd-text-main-color);
  }
  .form {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
    padding: var(--gr-space-sm);
    border-top: 1px solid var(--ksd-border-color);
  }
  .input {
    resize: vertical;
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
    font-size: 0.875rem;
    font-family: inherit;
  }
  .send {
    align-self: flex-end;
    padding: var(--gr-space-2xs) var(--gr-space-md);
    border: none;
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-accent-color);
    color: #fff;
    cursor: pointer;
    font-size: 0.875rem;
  }
  .send:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
