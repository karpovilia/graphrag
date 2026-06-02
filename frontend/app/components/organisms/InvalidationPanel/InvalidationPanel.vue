<script setup lang="ts">
  // §2.4 invalidation curation. Renders ONLY when a temporal diff carries
  // invalidated edges (edges that vanished WITH an EdgeInvalidation record
  // — disjoint from 'dead'). Each row surfaces the provenance and offers a
  // one-click revert, routed through an owned useEditCascade so the revert
  // gets the same ripple + latency feedback as every other journal write.

  import { computed } from "vue";
  import { useI18n } from "vue-i18n";

  import type { DeltaItem, GraphVariant, TemporalDiff } from "@/entities/api";
  import ErrorBanner from "@/components/molecules/ErrorBanner/ErrorBanner.vue";
  import LatencyBadge from "@/components/molecules/LatencyBadge/LatencyBadge.vue";
  import { useEditCascade, type EditCascade } from "@/composables/use-edit-cascade";
  import { formatRelativeTime } from "@/lib/format";

  const { t } = useI18n();

  type Props = {
    variant: GraphVariant;
    diff: TemporalDiff | null;
    actor?: string;
    /** §2.4 — shared page cascade so the revert's latency badge survives
     * after the panel collapses (the row drops out of the diff). Falls back
     * to an owned instance when used standalone. */
    cascade?: EditCascade;
  };
  const props = withDefaults(defineProps<Props>(), {
    actor: "user:ui",
  });

  const emit = defineEmits<{
    (e: "variant-changed", variant: GraphVariant): void;
    (e: "reverted", edgeId: string): void;
  }>();

  const cascade = props.cascade ?? useEditCascade(props.variant.id);

  const rows = computed<DeltaItem[]>(() =>
    (props.diff?.invalidated ?? []).filter((it) => it.kind === "edge"),
  );

  const show = computed(() => rows.value.length > 0);

  async function revert(item: DeltaItem) {
    try {
      const result = await cascade.revert(item.id, {
        expected_version: props.variant.version,
        actor: props.actor,
      });
      emit("variant-changed", result.variant);
      emit("reverted", String(item.id));
    } catch {
      // cascade.error holds the raw thrown error — surfaced via ErrorBanner.
    }
  }

  function shortId(id: string | null | undefined): string {
    return id ? String(id).slice(0, 8) : "—";
  }
</script>

<template>
  <section v-if="show" data-testid="invalidation-panel" :class="$style.panel">
    <header :class="$style.header">
      <h3 :class="$style.title">{{ t("invalidationPanel.title") }}</h3>
      <span :class="$style.count">{{ rows.length }}</span>
    </header>

    <ul :class="$style.list">
      <li
        v-for="item in rows"
        :key="item.id"
        data-testid="invalidation-row"
        :data-edge-id="item.id"
        :class="$style.row"
      >
        <div :class="$style.rowMain">
          <span :class="$style.edgeId" :title="item.id">
            {{ shortId(item.id) }}
          </span>
          <span v-if="item.invalidation" :class="$style.reason">
            {{ item.invalidation.reason }}
          </span>
          <span
            v-if="item.invalidation"
            :class="[$style.chip, item.invalidation.auto ? $style.chipAuto : $style.chipManual]"
          >
            {{ item.invalidation.auto ? t("invalidationPanel.auto") : t("invalidationPanel.manual") }}
          </span>
        </div>

        <div v-if="item.invalidation" :class="$style.provenance">
          <span :class="$style.muted">
            {{ t("invalidationPanel.when") }}:
            {{ formatRelativeTime(item.invalidation.at) }}
          </span>
          <span
            v-if="item.invalidation.superseded_by_edge_id"
            :class="$style.muted"
            :title="item.invalidation.superseded_by_edge_id ?? ''"
          >
            {{ t("invalidationPanel.supersededBy") }}:
            {{ shortId(item.invalidation.superseded_by_edge_id) }}
          </span>
          <span
            :class="$style.muted"
            :title="item.invalidation.ingestion_event_id"
          >
            {{ t("invalidationPanel.event") }}:
            {{ shortId(item.invalidation.ingestion_event_id) }}
          </span>
        </div>

        <div :class="$style.rowActions">
          <button
            type="button"
            data-testid="invalidation-revert"
            :class="$style.revert"
            :disabled="cascade.running.value"
            @click="revert(item)"
          >
            {{ t("invalidationPanel.revert") }}
          </button>
          <LatencyBadge
            v-if="cascade.lastTiming.value"
            :ms="cascade.lastTiming.value.recompute_ms"
            :node-count="cascade.lastTiming.value.node_count_after"
            :edge-count="cascade.lastTiming.value.edge_count_after"
          />
        </div>
      </li>
    </ul>

    <div
      v-if="cascade.error.value"
      data-testid="invalidation-error"
      :class="$style.errorWrap"
    >
      <ErrorBanner :error="cascade.error.value" />
    </div>
  </section>
</template>

<style lang="scss" module>
  .panel {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-xs);
    padding: var(--gr-space-sm);
    background: var(--ksd-card-bg-color);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-md);
  }

  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--gr-space-xs);
  }

  .title {
    margin: 0;
    font-size: 0.95rem;
    font-weight: 600;
  }

  .count {
    padding: 1px var(--gr-space-xs);
    border-radius: var(--gr-radius-sm);
    background: var(--gr-status-failed);
    color: white;
    font-size: 0.75rem;
    font-weight: 700;
  }

  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-xs);
  }

  .row {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
    padding: var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    // §0 grammar: invalidated reads as grey + struck-through.
    color: var(--ksd-text-secondary-color);
    text-decoration: line-through;
    text-decoration-color: rgba(107, 114, 128, 0.7);
  }

  .rowMain {
    display: flex;
    align-items: center;
    gap: var(--gr-space-2xs);
    flex-wrap: wrap;
  }

  .edgeId {
    font-family: ui-monospace, monospace;
    font-size: 0.75rem;
  }

  .reason {
    font-size: 0.8rem;
    text-decoration: none;
  }

  .chip {
    padding: 0 var(--gr-space-2xs);
    border-radius: var(--gr-radius-sm);
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    text-decoration: none;
  }

  .chipAuto {
    background: var(--gr-status-pending);
    color: white;
  }

  .chipManual {
    background: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
  }

  .provenance {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gr-space-xs);
    text-decoration: none;
  }

  .muted {
    color: var(--ksd-text-secondary-color);
    font-size: 0.72rem;
    text-decoration: none;
  }

  .rowActions {
    display: flex;
    align-items: center;
    gap: var(--gr-space-xs);
    text-decoration: none;
  }

  .revert {
    padding: 2px var(--gr-space-sm);
    border: 1px solid var(--ksd-accent-color);
    background: transparent;
    color: var(--ksd-accent-color);
    border-radius: var(--gr-radius-sm);
    font-size: 0.75rem;
    font-weight: 600;
    cursor: pointer;
    text-decoration: none;

    &:hover:not(:disabled) {
      background: var(--ksd-accent-color);
      color: var(--ksd-bg-color);
    }

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }

  .errorWrap {
    text-decoration: none;
  }
</style>
