<script setup lang="ts">
  // §0 legend — the key strip for the five delta encodings + the current
  // source label (time t_a→t_b / query evidence / edit cascade). One
  // legend, three sources: this is the visual assertion of the one-grammar
  // contribution. In diff mode it also shows TemporalDiff.counts chips.

  import { computed } from "vue";
  import { useI18n } from "vue-i18n";

  import type { TemporalDiff } from "@/entities/api";
  import {
    DELTA_COLORS,
    type DeltaSource,
  } from "@/components/organisms/LayeredGraph/lib/delta";

  const { t } = useI18n();

  type Props = {
    source: DeltaSource;
    diff?: TemporalDiff | null;
  };
  const props = withDefaults(defineProps<Props>(), { diff: null });

  // The five canonical encodings, in legend order.
  const keys = [
    { state: "born", color: DELTA_COLORS.born },
    { state: "dead", color: DELTA_COLORS.dead },
    { state: "persisted", color: "#9aa0a6" },
    { state: "moved_community", color: DELTA_COLORS.moved_community },
    { state: "evidence", color: "#1f77b4" },
  ] as const;

  const sourceLabel = computed(() => {
    if (props.source === "time") {
      if (props.diff)
        return t("deltaLegend.sourceTime", {
          a: new Date(props.diff.t_a).toLocaleDateString(),
          b: new Date(props.diff.t_b).toLocaleDateString(),
        });
      return t("deltaLegend.sourceTimePlain");
    }
    if (props.source === "query") return t("deltaLegend.sourceQuery");
    if (props.source === "edit") return t("deltaLegend.sourceEdit");
    return "";
  });
</script>

<template>
  <div :class="$style.legend" aria-label="Delta legend">
    <span :class="$style.source">{{ sourceLabel }}</span>
    <ul :class="$style.keys">
      <li v-for="k in keys" :key="k.state" :class="$style.key">
        <span :class="$style.swatch" :style="{ background: k.color ?? '#9aa0a6' }" />
        <span :class="$style.keyLabel">{{ t(`deltaLegend.${k.state}`) }}</span>
        <span
          v-if="diff && k.state in diff.counts"
          :class="$style.count"
        >
          {{ diff.counts[k.state as keyof typeof diff.counts] }}
        </span>
      </li>
    </ul>
  </div>
</template>

<style lang="scss" module>
  .legend {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--gr-space-sm);
    padding: var(--gr-space-2xs) var(--gr-space-md);
    background: var(--ksd-card-bg-color);
    border-top: 1px solid var(--ksd-border-color);
    font-size: 0.75rem;
  }

  .source {
    font-weight: 600;
    color: var(--ksd-text-secondary-color);
  }

  .keys {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gr-space-md);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .key {
    display: inline-flex;
    align-items: center;
    gap: var(--gr-space-2xs);
  }

  .swatch {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .keyLabel {
    color: var(--ksd-text-main-color);
  }

  .count {
    padding: 0 var(--gr-space-2xs);
    background: var(--ksd-bg-color);
    border-radius: var(--gr-radius-sm);
    color: var(--ksd-text-secondary-color);
  }
</style>
