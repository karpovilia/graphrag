<script setup lang="ts">
  import { useI18n } from "vue-i18n";

  import { useBuildWizard } from "@/composables/use-build-wizard";

  const { t } = useI18n();
  const wizard = useBuildWizard();
</script>

<template>
  <section :class="$style.step">
    <h2 :class="$style.title">{{ t("wizard.corpus.title") }}</h2>
    <p :class="$style.hint">{{ t("wizard.corpus.hint") }}</p>

    <label :class="$style.field">
      <span>{{ t("wizard.corpus.name") }}</span>
      <input
        v-model="wizard.data.value.corpus_name"
        type="text"
        :class="$style.input"
        :placeholder="t('wizard.corpus.namePlaceholder')"
        @input="wizard.invalidateDownstream(0)"
      />
    </label>

    <label :class="$style.field">
      <span>{{ t("wizard.corpus.description") }}</span>
      <textarea
        v-model="wizard.data.value.corpus_description"
        :class="$style.textarea"
        rows="3"
        :placeholder="t('wizard.corpus.descriptionPlaceholder')"
      />
    </label>

    <label :class="$style.field">
      <span>{{ t("wizard.corpus.language") }}</span>
      <select v-model="wizard.data.value.language" :class="$style.input">
        <option value="ru">{{ t("profile.languageRu") }}</option>
        <option value="en">{{ t("profile.languageEn") }}</option>
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
