<script setup lang="ts">
  import { computed } from "vue";
  import { useI18n } from "vue-i18n";

  import type { WizardStepDef, WizardStepStatus } from "@/composables/use-build-wizard";
  import AskAssistant from "./AskAssistant.vue";
  import WizardBreadcrumbs from "./WizardBreadcrumbs.vue";

  type Props = {
    title: string;
    steps: WizardStepDef[];
    statuses: WizardStepStatus[];
    currentIndex: number;
    busy?: boolean;
    canGoBack?: boolean;
    canAdvance?: boolean;
    advanceLabel?: string;
  };

  const props = withDefaults(defineProps<Props>(), {
    busy: false,
    canGoBack: true,
    canAdvance: true,
    advanceLabel: undefined,
  });

  const { t } = useI18n();
  // Caller-provided label wins; otherwise fall back to the localised
  // "Next" so consumers don't have to import useI18n just to set it.
  const advanceLabel = computed(
    () => props.advanceLabel ?? t("wizard.build.next"),
  );
  const backLabel = computed(() => t("wizard.build.back"));

  const emit = defineEmits<{
    (e: "navigate", index: number): void;
    (e: "back"): void;
    (e: "advance"): void;
  }>();
</script>

<template>
  <div :class="$style.frame">
    <header :class="$style.header">
      <h1 :class="$style.title">{{ title }}</h1>
      <AskAssistant :step-context="steps[currentIndex]?.label" />
    </header>

    <WizardBreadcrumbs
      :steps="steps"
      :statuses="statuses"
      :current-index="currentIndex"
      @navigate="(i) => emit('navigate', i)"
    />

    <main :class="$style.body">
      <slot />
    </main>

    <footer :class="$style.footer">
      <button
        type="button"
        :class="$style.secondary"
        :disabled="!props.canGoBack || props.currentIndex === 0 || props.busy"
        @click="emit('back')"
      >
        {{ backLabel }}
      </button>
      <button
        type="button"
        :class="$style.primary"
        :disabled="!props.canAdvance || props.busy"
        @click="emit('advance')"
      >
        {{ props.busy ? "…" : advanceLabel }}
      </button>
    </footer>
  </div>
</template>

<style lang="scss" module>
  .frame {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-lg);
    padding: var(--gr-space-xl);
    overflow-y: auto;
    flex: 1;
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--gr-space-md);
  }

  .title {
    margin: 0;
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--ksd-text-main-color);
  }

  .body {
    flex: 1;
    background: var(--ksd-card-bg-color);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-md);
    padding: var(--gr-space-lg);
    box-shadow: var(--gr-shadow-sm);
  }

  .footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--gr-space-md);
  }

  .primary,
  .secondary {
    padding: var(--gr-space-sm) var(--gr-space-lg);
    border-radius: var(--gr-radius-sm);
    font-weight: 600;
    cursor: pointer;
    transition: filter 0.15s ease;
    border: 1px solid transparent;
  }

  .primary {
    background: var(--ksd-accent-color);
    color: var(--ksd-bg-color);

    &:hover:not(:disabled) {
      filter: brightness(1.05);
    }

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }

  .secondary {
    background: transparent;
    border-color: var(--ksd-border-color);
    color: var(--ksd-text-main-color);

    &:hover:not(:disabled) {
      border-color: var(--ksd-accent-color);
    }

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }
</style>
