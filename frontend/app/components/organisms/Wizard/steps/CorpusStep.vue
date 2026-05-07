<script setup lang="ts">
  import { useBuildWizard } from "@/composables/use-build-wizard";

  const wizard = useBuildWizard();
</script>

<template>
  <section :class="$style.step">
    <h2 :class="$style.title">Корпус</h2>
    <p :class="$style.hint">
      Назовите корпус и опишите что в нём — это поможет найти его в списке
      позже.
    </p>

    <label :class="$style.field">
      <span>Название</span>
      <input
        v-model="wizard.data.value.corpus_name"
        type="text"
        :class="$style.input"
        placeholder="Например, HSE podcast — выпуск 12"
        @input="wizard.invalidateDownstream(0)"
      />
    </label>

    <label :class="$style.field">
      <span>Описание (необязательно)</span>
      <textarea
        v-model="wizard.data.value.corpus_description"
        :class="$style.textarea"
        rows="3"
        placeholder="Что внутри: сколько эпизодов, период, источник…"
      />
    </label>

    <label :class="$style.field">
      <span>Язык</span>
      <select v-model="wizard.data.value.language" :class="$style.input">
        <option value="ru">русский</option>
        <option value="en">english</option>
      </select>
    </label>
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

  .field {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);

    > span {
      font-size: 0.875rem;
      color: var(--ksd-text-secondary-color);
    }
  }

  .input,
  .textarea {
    padding: var(--gr-space-xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
    font-family: inherit;
  }

  .textarea {
    resize: vertical;
  }
</style>
