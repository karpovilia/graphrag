<script setup lang="ts">
  import { useAskWizard } from "@/composables/use-ask-wizard";

  const wizard = useAskWizard();

  const examples = [
    "Кто чем занимается в этом подкасте?",
    "Какие основные темы обсуждались?",
    "Как связаны главные действующие лица?",
    "Перечисли организации, упомянутые в тексте.",
  ];
</script>

<template>
  <section :class="$style.step">
    <h2 :class="$style.title">Вопрос</h2>
    <p :class="$style.hint">
      Сформулируйте вопрос на естественном языке. Reasoner
      <strong>{{ wizard.data.value.reasoner }}</strong> вернёт ответ с
      evidence-узлами; в MoE-режиме каждый вариант ответит независимо, а
      <strong>{{ wizard.data.value.aggregator }}</strong> сольёт результаты.
    </p>

    <textarea
      v-model="wizard.data.value.query"
      :class="$style.textarea"
      rows="4"
      placeholder="Например: «Кто такой Иван Иванов?» или «Какие темы пересекаются между эпизодами?»"
      @input="wizard.invalidateDownstream(3)"
    />

    <div :class="$style.examples">
      <span :class="$style.label">Шпаргалка:</span>
      <button
        v-for="(ex, i) in examples"
        :key="i"
        type="button"
        :class="$style.exampleBtn"
        @click="
          wizard.data.value.query = ex;
          wizard.invalidateDownstream(3);
        "
      >
        {{ ex }}
      </button>
    </div>
  </section>
</template>

<style lang="scss" module>
  .step {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-md);
  }

  .title {
    margin: 0;
    font-size: 1.25rem;
    font-weight: 600;
  }

  .hint {
    margin: 0;
    color: var(--ksd-text-secondary-color);
  }

  .textarea {
    padding: var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
    font-family: inherit;
    font-size: 1rem;
    line-height: 1.5;
    resize: vertical;
  }

  .examples {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gr-space-2xs);
    align-items: center;
  }

  .label {
    font-size: 0.875rem;
    color: var(--ksd-text-secondary-color);
  }

  .exampleBtn {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    font-size: 0.875rem;
    border: 1px solid var(--ksd-border-color);
    background: transparent;
    border-radius: var(--gr-radius-sm);
    color: var(--ksd-text-main-color);
    cursor: pointer;

    &:hover {
      border-color: var(--ksd-accent-color);
    }
  }
</style>
