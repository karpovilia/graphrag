<script setup lang="ts">
  import { useAsyncData } from "nuxt/app";
  import { computed, ref, watch } from "vue";
  import { useRoute } from "vue-router";
  import { useI18n } from "vue-i18n";

  import LayeredGraph from "@/components/organisms/LayeredGraph/LayeredGraph.vue";
  import LayersPanel from "@/components/organisms/LayersPanel/LayersPanel.vue";
  import NodeDrawer from "@/components/organisms/NodeDrawer/NodeDrawer.vue";
  import SuggestionsSidebar from "@/components/organisms/SuggestionsSidebar/SuggestionsSidebar.vue";
  import { themeBehaviorSubject } from "@/entities/tech";
  import { useApi } from "@/lib/api-client";
  import { formatNumber } from "@/lib/format";
  import type { GraphVariant, Node } from "@/entities/api";

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

  const selectedNodes = ref<id[]>([]);
  const selectedLink = ref<id | null>(null);
  const showSuggestions = ref(false);
  const showLayers = ref(false);
  const highlightedNodes = ref<id[]>([]);

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

      <div :class="$style.canvas">
        <LayeredGraph
          :nodes="nodes"
          :edges="edges"
          :theme="theme"
          :variant-id="variant.id"
          :highlighted-node-ids="highlightedNodes"
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

  .canvas {
    flex: 1;
    overflow: hidden;
    position: relative;
  }

  .error {
    padding: var(--gr-space-xl);
    color: var(--gr-status-failed);
  }
</style>
