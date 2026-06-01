<script setup lang="ts">
  // §2.3 latency badge — the transient pill shown after every journal
  // write (rename / accept / revert). Presentational only: the parent
  // owns the cascade timing and re-renders this when it changes.
  //
  // Tier (for color + e2e color assertion without reading CSS):
  //   ms < 50   → 'fast'  (green, --gr-status-success)
  //   ms < 500  → 'mid'   (amber, --gr-status-warn)
  //   else      → 'slow'  (red,   --gr-status-failed)
  //
  // The badge stays in the DOM (keeps its data-testid) but auto-fades to
  // data-state='faded' after ~2.5s so the cascade reads as momentary.

  import { computed, onBeforeUnmount, ref, watch } from "vue";
  import { useI18n } from "vue-i18n";

  const { t } = useI18n();

  type Props = {
    ms: number;
    nodeCount?: number;
    edgeCount?: number;
  };
  const props = defineProps<Props>();

  const tier = computed<"fast" | "mid" | "slow">(() => {
    if (props.ms < 50) return "fast";
    if (props.ms < 500) return "mid";
    return "slow";
  });

  const faded = ref(false);
  let fadeTimer: ReturnType<typeof setTimeout> | null = null;

  function armFade() {
    if (fadeTimer) clearTimeout(fadeTimer);
    faded.value = false;
    fadeTimer = setTimeout(() => {
      faded.value = true;
    }, 2500);
  }

  // Re-arm whenever a fresh timing arrives (ms changes).
  watch(() => props.ms, armFade, { immediate: true });
  onBeforeUnmount(() => {
    if (fadeTimer) clearTimeout(fadeTimer);
  });

  const hasDelta = computed(
    () => props.nodeCount !== undefined || props.edgeCount !== undefined,
  );
</script>

<template>
  <span
    data-testid="latency-badge"
    :data-tier="tier"
    :data-state="faded ? 'faded' : 'shown'"
    :class="[$style.badge, $style[`tier_${tier}`], faded ? $style.faded : '']"
    :title="t('latency.tip')"
    :aria-label="t('latency.badgeAria', { ms })"
  >
    <span :class="$style.ms">{{ ms }} {{ t("latency.unit") }}</span>
    <span v-if="hasDelta" :class="$style.delta">
      · {{ nodeCount ?? 0 }}n {{ edgeCount ?? 0 }}e
    </span>
  </span>
</template>

<style lang="scss" module>
  .badge {
    display: inline-flex;
    align-items: baseline;
    gap: var(--gr-space-2xs);
    padding: 1px var(--gr-space-xs);
    border-radius: var(--gr-radius-sm);
    font-size: 0.72rem;
    font-weight: 600;
    line-height: 1.4;
    border: 1px solid currentColor;
    background: var(--ksd-card-bg-color);
    white-space: nowrap;
    transition: opacity 0.4s ease;
  }

  .faded {
    opacity: 0.35;
  }

  .tier_fast {
    color: var(--gr-status-success);
  }

  .tier_mid {
    color: var(--gr-status-warn);
  }

  .tier_slow {
    color: var(--gr-status-failed);
  }

  .ms {
    font-variant-numeric: tabular-nums;
  }

  .delta {
    color: var(--ksd-text-secondary-color);
    font-weight: 400;
  }
</style>
