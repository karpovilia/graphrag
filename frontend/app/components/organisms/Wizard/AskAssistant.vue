<script setup lang="ts">
  import { ref } from "vue";

  type Props = {
    /** Free-text label of the current wizard step — surfaced to the
     * assistant as system context. Phase 6 ships the affordance + UX;
     * the LLM-without-graph endpoint that powers it is wired in 6.x.
     */
    stepContext?: string;
  };

  const props = defineProps<Props>();

  const open = ref(false);
  const question = ref("");
  const messages = ref<{ role: "user" | "assistant"; text: string }[]>([]);

  function toggle() {
    open.value = !open.value;
  }

  function ask() {
    const q = question.value.trim();
    if (!q) return;
    messages.value.push({ role: "user", text: q });
    question.value = "";
    // Phase 6 stub. The real wiring (POST /api/assistant or piggy-backing
    // /api/reason against a placeholder corpus) lands as soon as the
    // backend exposes a context-free chat endpoint.
    messages.value.push({
      role: "assistant",
      text:
        "(черновик ответа) Чат-помощник пока не подключён к LLM. " +
        `Контекст шага: ${props.stepContext ?? "—"}.`,
    });
  }
</script>

<template>
  <div :class="$style.host">
    <button
      type="button"
      :class="$style.toggle"
      :aria-expanded="open"
      @click="toggle"
    >
      💬 спросить ассистента
    </button>

    <aside v-if="open" :class="$style.panel" aria-label="Чат с ассистентом">
      <header :class="$style.header">
        <span>Ассистент</span>
        <button type="button" :class="$style.close" @click="open = false">×</button>
      </header>

      <p v-if="stepContext" :class="$style.context">
        Контекст шага: <strong>{{ stepContext }}</strong>
      </p>

      <ul :class="$style.thread">
        <li
          v-for="(m, i) in messages"
          :key="i"
          :class="[$style.message, $style[`message_${m.role}`]]"
        >
          {{ m.text }}
        </li>
        <li v-if="!messages.length" :class="$style.empty">
          Задайте вопрос про текущий шаг — например, «какой Builder подойдёт
          для коротких документов?».
        </li>
      </ul>

      <form
        :class="$style.input"
        @submit.prevent="ask"
      >
        <input
          v-model="question"
          type="text"
          placeholder="Ваш вопрос…"
          :class="$style.field"
        />
        <button type="submit" :class="$style.send" :disabled="!question.trim()">
          Send
        </button>
      </form>
    </aside>
  </div>
</template>

<style lang="scss" module>
  .host {
    position: relative;
  }

  .toggle {
    padding: var(--gr-space-xs) var(--gr-space-md);
    background: var(--ksd-card-bg-color);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    cursor: pointer;
    color: var(--ksd-text-main-color);
    font-size: 0.875rem;

    &:hover {
      border-color: var(--ksd-accent-color);
    }
  }

  .panel {
    position: fixed;
    right: var(--gr-space-md);
    bottom: var(--gr-space-md);
    width: 360px;
    max-height: 60vh;
    background: var(--ksd-card-bg-color);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-md);
    box-shadow: var(--gr-shadow-lg);
    display: flex;
    flex-direction: column;
    z-index: 1000;
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--gr-space-sm) var(--gr-space-md);
    border-bottom: 1px solid var(--ksd-border-color);
    font-weight: 600;
  }

  .close {
    background: transparent;
    border: none;
    color: var(--ksd-text-secondary-color);
    cursor: pointer;
    font-size: 1.25rem;
    line-height: 1;
  }

  .context {
    margin: 0;
    padding: var(--gr-space-xs) var(--gr-space-md);
    font-size: 0.8rem;
    color: var(--ksd-text-secondary-color);
    background: rgba(255, 255, 255, 0.04);
  }

  .thread {
    list-style: none;
    margin: 0;
    padding: var(--gr-space-md);
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-sm);
  }

  .empty {
    color: var(--ksd-text-secondary-color);
    font-size: 0.875rem;
  }

  .message {
    padding: var(--gr-space-xs) var(--gr-space-sm);
    border-radius: var(--gr-radius-sm);
    max-width: 85%;
    font-size: 0.875rem;
    line-height: 1.4;
  }

  .message_user {
    background: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
    align-self: flex-end;
  }

  .message_assistant {
    background: rgba(255, 255, 255, 0.05);
    color: var(--ksd-text-main-color);
  }

  .input {
    display: flex;
    gap: var(--gr-space-2xs);
    padding: var(--gr-space-sm);
    border-top: 1px solid var(--ksd-border-color);
  }

  .field {
    flex: 1;
    padding: var(--gr-space-xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
  }

  .send {
    padding: var(--gr-space-xs) var(--gr-space-md);
    border: none;
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
    cursor: pointer;
    font-weight: 600;

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }
</style>
