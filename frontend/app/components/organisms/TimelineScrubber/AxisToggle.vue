<script setup lang="ts">
  // §2.1 axis toggle — event-time (T) ↔ transaction-time (T'). Two-segment
  // control bound to the `axis` model. The distinction (ADR-0002): T =
  // when a fact was true in the world (event_time); T' = when we ingested
  // it (ingested_at). Changing it re-sorts the timeline + re-fetches.

  import { useI18n } from "vue-i18n";

  import type { TimeAxis } from "@/entities/api";

  const { t } = useI18n();
  const axis = defineModel<TimeAxis>({ default: "tx" });
</script>

<template>
  <div
    :class="$style.toggle"
    role="group"
    data-testid="axis-toggle"
    :aria-label="t('timeline.axisAria')"
  >
    <button
      type="button"
      :class="[$style.seg, axis === 'valid' ? $style.seg_active : '']"
      :title="t('timeline.axisValidTip')"
      @click="axis = 'valid'"
    >
      {{ t("timeline.axisValid") }}
    </button>
    <button
      type="button"
      :class="[$style.seg, axis === 'tx' ? $style.seg_active : '']"
      :title="t('timeline.axisTxTip')"
      @click="axis = 'tx'"
    >
      {{ t("timeline.axisTx") }}
    </button>
  </div>
</template>

<style lang="scss" module>
  .toggle {
    display: inline-flex;
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    overflow: hidden;
  }

  .seg {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    background: transparent;
    border: none;
    cursor: pointer;
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--ksd-text-main-color);

    &:hover {
      color: var(--ksd-accent-color);
    }
  }

  .seg_active {
    background: var(--ksd-accent-color);
    color: var(--ksd-bg-color);

    &:hover {
      color: var(--ksd-bg-color);
    }
  }
</style>
