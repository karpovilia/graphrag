<script setup lang="ts">
  import { computed } from "vue";
  import { useI18n } from "vue-i18n";

  import { useAskWizard } from "@/composables/use-ask-wizard";

  const { t } = useI18n();
  const wizard = useAskWizard();

  const cards = computed(() => [
    {
      mode: "single" as const,
      title: "Single",
      summary: t("wizard.ask.modeSingleSummary"),
      desc: t("wizard.ask.modeSingleDescription"),
    },
    {
      mode: "moe" as const,
      title: "Mixture of Experts",
      summary: t("wizard.ask.modeMoeSummary"),
      desc: t("wizard.ask.modeMoeDescription"),
    },
  ]);
</script>

<template>
  <section :class="$style.step">
    <h2 :class="$style.title">{{ t("wizard.ask.modeTitle") }}</h2>

    <ul :class="$style.cards">
      <li
        v-for="c in cards"
        :key="c.mode"
        :class="[
          $style.card,
          wizard.data.value.mode === c.mode ? $style.card_active : '',
        ]"
        @click="
          wizard.data.value.mode = c.mode;
          wizard.invalidateDownstream(0);
        "
      >
        <header :class="$style.cardHeader">
          <strong>{{ c.title }}</strong>
        </header>
        <p :class="$style.summary">{{ c.summary }}</p>
        <p :class="$style.desc">{{ c.desc }}</p>
      </li>
    </ul>
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

  .cards {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: var(--gr-space-md);
  }

  .card {
    padding: var(--gr-space-md);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-md);
    cursor: pointer;
    background: var(--ksd-bg-color);
    transition: border-color 0.15s ease;

    &:hover {
      border-color: var(--ksd-accent-color);
    }
  }

  .card_active {
    border-color: var(--ksd-accent-color);
    background: rgba(31, 119, 180, 0.08);
  }

  .cardHeader {
    margin-bottom: var(--gr-space-xs);
    font-size: 1.1rem;
  }

  .summary {
    margin: 0 0 var(--gr-space-xs);
    color: var(--ksd-text-main-color);
    font-weight: 500;
  }

  .desc {
    margin: 0;
    font-size: 0.875rem;
    color: var(--ksd-text-secondary-color);
  }
</style>
