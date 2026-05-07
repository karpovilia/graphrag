<script setup lang="ts">
  import type { WizardStepDef, WizardStepStatus } from "@/composables/use-build-wizard";

  type Props = {
    steps: WizardStepDef[];
    statuses: WizardStepStatus[];
    currentIndex: number;
  };

  const props = defineProps<Props>();
  const emit = defineEmits<{ (e: "navigate", index: number): void }>();

  function classFor(index: number) {
    const status = props.statuses[index] ?? "pending";
    return [
      "crumb",
      `crumb_${status}`,
      index === props.currentIndex ? "crumb_active" : "",
    ];
  }
</script>

<template>
  <nav :class="$style.breadcrumbs" aria-label="Шаги визарда">
    <ol :class="$style.list">
      <li
        v-for="(step, index) in steps"
        :key="step.id"
        :class="$style[classFor(index).filter(Boolean).join(' ')] || ''"
      >
        <button
          type="button"
          :class="[
            $style.crumb,
            $style[`crumb_${statuses[index] ?? 'pending'}`],
            index === currentIndex ? $style.crumb_active : '',
          ]"
          @click="emit('navigate', index)"
        >
          <span :class="$style.idx">{{ index + 1 }}</span>
          <span :class="$style.label">{{ step.label }}</span>
          <span
            v-if="statuses[index] === 'needs_confirmation'"
            :class="$style.confirmTag"
            title="Состояние шага могло измениться — подтвердите"
          >
            !
          </span>
        </button>
        <span v-if="index < steps.length - 1" :class="$style.sep">→</span>
      </li>
    </ol>
  </nav>
</template>

<style lang="scss" module>
  .breadcrumbs {
    width: 100%;
  }

  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--gr-space-2xs);
  }

  .crumb {
    display: inline-flex;
    align-items: center;
    gap: var(--gr-space-2xs);
    padding: var(--gr-space-xs) var(--gr-space-md);
    border: 1px solid var(--ksd-border-color);
    background: transparent;
    border-radius: var(--gr-radius-sm);
    font-size: 0.875rem;
    color: var(--ksd-text-secondary-color);
    cursor: pointer;
    transition: background 0.15s ease;

    &:hover {
      background: var(--ksd-card-bg-color);
    }
  }

  .crumb_active {
    background: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
    border-color: var(--ksd-accent-color);

    .idx,
    .label {
      color: var(--ksd-bg-color);
    }
  }

  .crumb_completed {
    border-color: var(--gr-status-success);
    color: var(--gr-status-success);
  }

  .crumb_in_progress {
    border-color: var(--gr-status-running);
  }

  .crumb_needs_confirmation {
    border-color: var(--gr-status-running);
    background: rgba(245, 158, 11, 0.08);
  }

  .idx {
    font-weight: 700;
    width: 1.5em;
    height: 1.5em;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: rgba(255, 255, 255, 0.15);
  }

  .label {
    font-weight: 500;
  }

  .confirmTag {
    margin-left: var(--gr-space-2xs);
    width: 1.2em;
    height: 1.2em;
    border-radius: 50%;
    background: var(--gr-status-running);
    color: white;
    font-size: 0.7rem;
    font-weight: 700;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .sep {
    color: var(--ksd-text-secondary-color);
    margin: 0 var(--gr-space-2xs);
  }
</style>
