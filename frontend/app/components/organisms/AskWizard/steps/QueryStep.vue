<script setup lang="ts">
  import { computed } from "vue";
  import { useI18n } from "vue-i18n";

  import { useAskWizard } from "@/composables/use-ask-wizard";

  const { t } = useI18n();
  const wizard = useAskWizard();

  const examples = computed(() => [
    t("wizard.ask.querySuggestion1"),
    t("wizard.ask.querySuggestion2"),
    t("wizard.ask.querySuggestion3"),
    t("wizard.ask.querySuggestion4"),
  ]);
</script>

<template>
  <section :class="$style.step">
    <h2 :class="$style.title">{{ t("wizard.ask.queryTitle") }}</h2>
    <p :class="$style.hint">
      <strong>{{ wizard.data.value.reasoner }}</strong> ·
      <strong>{{ wizard.data.value.aggregator }}</strong>
    </p>

    <textarea
      v-model="wizard.data.value.query"
      :class="$style.textarea"
      rows="4"
      :placeholder="t('wizard.ask.queryPlaceholder')"
      @input="wizard.invalidateDownstream(3)"
    />

    <div :class="$style.examples">
      <span :class="$style.label">{{ t("wizard.ask.querySuggestionsHint") }}</span>
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
