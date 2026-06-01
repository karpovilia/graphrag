<script setup lang="ts">
  import { useAsyncData } from "nuxt/app";
  import { computed, ref, watch } from "vue";
  import { useRoute } from "vue-router";
  import { useI18n } from "vue-i18n";

  import LayeredGraph from "@/components/organisms/LayeredGraph/LayeredGraph.vue";
  import LayersPanel from "@/components/organisms/LayersPanel/LayersPanel.vue";
  import NodeDrawer from "@/components/organisms/NodeDrawer/NodeDrawer.vue";
  import SuggestionsSidebar from "@/components/organisms/SuggestionsSidebar/SuggestionsSidebar.vue";
  import TimelineScrubber from "@/components/organisms/TimelineScrubber/TimelineScrubber.vue";
  import AxisToggle from "@/components/organisms/TimelineScrubber/AxisToggle.vue";
  import DeltaLegend from "@/components/organisms/DeltaLegend/DeltaLegend.vue";
  import { themeBehaviorSubject } from "@/entities/tech";
  import { useApi } from "@/lib/api-client";
  import { formatNumber } from "@/lib/format";
  import type { Edge, GraphVariant, Node, TimeAxis } from "@/entities/api";
  import { useTemporalWindow } from "@/composables/use-temporal-window";
  import { useQueryDelta } from "@/composables/use-query-delta";
  import type { DeltaSource, DeltaState } from "@/components/organisms/LayeredGraph/lib/delta";

  const route = useRoute();
  const variantId = String(route.params.id);
  const api = useApi();
  const theme = themeBehaviorSubject.useSubscribe();
  const { t } = useI18n();

  const { data: variant, error: variantError } =
    await useAsyncData(`variant:${variantId}`, () => api.graphs.get(variantId));
  const { data: nodes, refresh: refreshNodes, error: nodesError } =
    await useAsyncData(`nodes:${variantId}`, () =>
      api.graphs.listNodes(variantId),
    );
  const { data: edges, refresh: refreshEdges, error: edgesError } =
    await useAsyncData(`edges:${variantId}`, () =>
      api.graphs.listEdges(variantId),
    );

  // §2.1 timeline — best-effort: if the backend doesn't expose the
  // endpoint yet, fall back to an empty axis (scrubber stays hidden).
  const { data: timeline, refresh: refreshTimeline } = await useAsyncData(
    `timeline:${variantId}`,
    () => api.graphs.timeline(variantId, "tx").catch(() => []),
  );

  const selectedNodes = ref<id[]>([]);
  const selectedLink = ref<id | null>(null);
  const showSuggestions = ref(false);
  const showLayers = ref(false);
  const showTimeline = ref(false);
  const highlightedNodes = ref<id[]>([]);

  // §2.1 temporal window (shared, observable, lifted out of LayeredGraph).
  const tw = useTemporalWindow(variantId);
  // scrubber model: ISO (instant) or [t_a, t_b] (diff).
  const scrubModel = ref<string | [string, string] | null>(null);
  watch(scrubModel, (v) => {
    if (v != null) tw.scrubTo(v);
  });
  function onAxisChange(next: TimeAxis) {
    tw.setAxis(next);
    refreshTimeline();
  }

  // §2.2 query-delta bridge (evidence highlight from the ask wizard).
  const queryDelta = useQueryDelta();
  const queryDeltaActive = computed(() => route.query.queryDelta === "1");

  // The delta overlay fed to LayeredGraph. Time diff wins when active;
  // otherwise the query-delta evidence index (if ?queryDelta=1).
  const deltaIndex = computed<Map<string, DeltaState> | null>(() => {
    if (tw.mode.value === "diff" && tw.deltaIndex.value) return tw.deltaIndex.value;
    if (queryDeltaActive.value) return queryDelta.buildDeltaIndex(variantId);
    return null;
  });
  const deltaSource = computed<DeltaSource>(() => {
    if (tw.mode.value === "diff" && tw.deltaIndex.value) return "time";
    if (queryDeltaActive.value && queryDelta.entryFor(variantId)) return "query";
    return null;
  });

  // Instant scrub SHRINKS the visible graph to the facts live at t (R1).
  const visibleNodes = computed<Node[]>(() => {
    const all = nodes.value ?? [];
    const ids = tw.visibleNodeIds.value;
    if (tw.mode.value !== "instant" || !ids) return all;
    return all.filter((n) => ids.has(String(n.id)));
  });
  const visibleEdges = computed<Edge[]>(() => {
    const all = edges.value ?? [];
    const ids = tw.visibleEdgeIds.value;
    if (tw.mode.value !== "instant" || !ids) return all;
    return all.filter((e) => ids.has(String(e.id)));
  });

  const selectedNode = computed<Node | null>(() => {
    if (selectedNodes.value.length !== 1) return null;
    const id = selectedNodes.value[0];
    return (nodes.value ?? []).find((n) => n.id === id) ?? null;
  });

  const error = variantError.value || nodesError.value || edgesError.value;

  function onVariantChanged(v: GraphVariant) {
    if (variant.value) variant.value = v;
    refreshNodes();
    refreshEdges();
  }

  // Force-reload graph payloads on every version bump (curation op
  // applied) so the canvas reflects post-edit state.
  watch(
    () => variant.value?.version,
    () => {
      refreshNodes();
      refreshEdges();
      refreshTimeline();
    },
  );
</script>

<template>
  <div :class="$style.page">
    <header :class="$style.header" v-if="variant">
      <div :class="$style.headerMain">
        <NuxtLink to="/corpora" :class="$style.back">{{ t("graph.backToCorpora") }}</NuxtLink>
        <h1 :class="$style.title">{{ variant.name }}</h1>
        <p :class="$style.muted">
          builder: <code>{{ variant.builder }}</code> · cleaners:
          <code>{{ variant.cleaner_chain.join(" → ") || "—" }}</code> · clusterer:
          <code>{{ variant.clusterer ?? "—" }}</code>
        </p>
      </div>

      <div :class="$style.headerActions">
        <button
          type="button"
          :class="[$style.toggle, showSuggestions ? $style.toggle_active : '']"
          @click="showSuggestions = !showSuggestions"
        >
          {{ showSuggestions ? t("graph.hideSuggestions") : t("graph.showSuggestions") }}
        </button>
        <button
          type="button"
          :class="[$style.toggle, showLayers ? $style.toggle_active : '']"
          @click="showLayers = !showLayers"
        >
          {{ t("layersPanel.open") }}
        </button>
        <button
          v-if="timeline && timeline.length"
          type="button"
          :class="[$style.toggle, showTimeline ? $style.toggle_active : '']"
          @click="showTimeline = !showTimeline"
        >
          {{ t("timeline.toggle") }}
        </button>
        <a
          :href="api.graphs.exportJournalUrl(variant.id, 'json')"
          target="_blank"
          rel="noopener"
          :class="$style.exportBtn"
        >
          {{ t("graph.exportJournal") }}
        </a>
      </div>

      <dl :class="$style.metrics">
        <div>
          <dt>Узлов</dt>
          <dd>{{ formatNumber(variant.node_count) }}</dd>
        </div>
        <div>
          <dt>Рёбер</dt>
          <dd>{{ formatNumber(variant.edge_count) }}</dd>
        </div>
        <div>
          <dt>Версия</dt>
          <dd>v{{ variant.version }}</dd>
        </div>
      </dl>
    </header>

    <div v-if="error" :class="$style.error">
      Не удалось загрузить вариант: {{ error.message }}
    </div>

    <div v-else-if="variant && nodes && edges" :class="$style.body">
      <SuggestionsSidebar
        v-if="showSuggestions"
        :variant="variant"
        @variant-changed="onVariantChanged"
        @highlight="(ids) => (highlightedNodes = ids)"
      />

      <div :class="$style.canvasWrap">
        <div :class="$style.canvas">
          <LayeredGraph
            :nodes="visibleNodes"
            :edges="visibleEdges"
            :theme="theme"
            :variant-id="variant.id"
            :highlighted-node-ids="highlightedNodes"
            :delta-index="deltaIndex"
            :delta-source="deltaSource"
            v-model:selectedNodes="selectedNodes"
            v-model:selectedLink="selectedLink"
          />
          <LayersPanel
            v-if="showLayers"
            :nodes="nodes"
            :edges="edges"
            @close="showLayers = false"
            @select-node="(id) => (selectedNodes = [id])"
          />
        </div>

        <DeltaLegend
          v-if="deltaSource"
          :source="deltaSource"
          :diff="tw.lastDiff.value"
        />

        <div v-if="showTimeline && timeline && timeline.length" :class="$style.timeline">
          <div :class="$style.timelineHead">
            <AxisToggle :model-value="tw.axis.value" @update:model-value="onAxisChange" />
            <div :class="$style.timelineModes">
              <button
                type="button"
                :class="[$style.modeBtn, tw.mode.value === 'instant' ? $style.modeBtn_active : '']"
                @click="tw.mode.value = 'instant'; tw.reset()"
              >
                {{ t("timeline.modeInstant") }}
              </button>
              <button
                type="button"
                :class="[$style.modeBtn, tw.mode.value === 'diff' ? $style.modeBtn_active : '']"
                @click="tw.mode.value = 'diff'"
              >
                {{ t("timeline.modeDiff") }}
              </button>
              <button type="button" :class="$style.modeBtn" @click="tw.reset()">
                {{ t("timeline.clear") }}
              </button>
            </div>
          </div>
          <TimelineScrubber
            v-model="scrubModel"
            :events="timeline"
            :axis="tw.axis.value"
            :mode="tw.mode.value"
            :playing="tw.playing.value"
            @update:playing="(p) => (tw.playing.value = p)"
          />
        </div>
      </div>

      <NodeDrawer
        v-if="selectedNode"
        :node="selectedNode"
        :variant="variant"
        @close="selectedNodes = []"
        @variant-changed="onVariantChanged"
      />
    </div>
  </div>
</template>

<style lang="scss" module>
  .page {
    display: flex;
    flex-direction: column;
    flex: 1;
    overflow: hidden;
  }

  .header {
    display: grid;
    grid-template-columns: 1fr auto auto;
    align-items: flex-start;
    gap: var(--gr-space-md);
    padding: var(--gr-space-md) var(--gr-space-xl);
    border-bottom: 1px solid var(--ksd-border-color);
    flex-shrink: 0;
  }

  .headerMain {
    min-width: 0;
  }

  .back {
    display: inline-block;
    margin-bottom: var(--gr-space-2xs);
    font-size: 0.875rem;
    color: var(--ksd-text-secondary-color);
    text-decoration: none;

    &:hover {
      color: var(--ksd-accent-color);
    }
  }

  .title {
    margin: 0 0 var(--gr-space-2xs);
    font-size: 1.5rem;
    font-weight: 700;
  }

  .muted {
    margin: 0;
    color: var(--ksd-text-secondary-color);
    font-size: 0.875rem;

    code {
      font-family: ui-monospace, monospace;
      background: var(--ksd-card-bg-color);
      padding: 0 var(--gr-space-2xs);
      border-radius: 3px;
    }
  }

  .headerActions {
    display: flex;
    align-items: center;
    gap: var(--gr-space-xs);
  }

  .toggle,
  .exportBtn {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    background: transparent;
    border-radius: var(--gr-radius-sm);
    cursor: pointer;
    color: var(--ksd-text-main-color);
    font-size: 0.875rem;
    text-decoration: none;

    &:hover {
      border-color: var(--ksd-accent-color);
      color: var(--ksd-accent-color);
    }
  }

  .toggle_active {
    background: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
    border-color: var(--ksd-accent-color);

    &:hover {
      color: var(--ksd-bg-color);
    }
  }

  .metrics {
    display: flex;
    gap: var(--gr-space-lg);
    margin: 0;

    dt {
      font-size: 0.7rem;
      color: var(--ksd-text-secondary-color);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    dd {
      margin: 0;
      font-size: 1.25rem;
      font-weight: 600;
    }
  }

  .body {
    flex: 1;
    display: flex;
    overflow: hidden;
  }

  .canvasWrap {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    position: relative;
  }

  .canvas {
    flex: 1;
    overflow: hidden;
    position: relative;
  }

  .timeline {
    flex-shrink: 0;
    border-top: 1px solid var(--ksd-border-color);
    background: var(--ksd-bg-color);
  }

  .timelineHead {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--gr-space-sm);
    padding: var(--gr-space-2xs) var(--gr-space-md) 0;
  }

  .timelineModes {
    display: flex;
    gap: var(--gr-space-2xs);
  }

  .modeBtn {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    background: transparent;
    border-radius: var(--gr-radius-sm);
    cursor: pointer;
    color: var(--ksd-text-main-color);
    font-size: 0.8rem;

    &:hover {
      border-color: var(--ksd-accent-color);
    }
  }

  .modeBtn_active {
    background: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
    border-color: var(--ksd-accent-color);
  }

  .error {
    padding: var(--gr-space-xl);
    color: var(--gr-status-failed);
  }
</style>
