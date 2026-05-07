<script setup lang="ts">
  import { useAsyncData } from "nuxt/app";
  import { useRoute } from "vue-router";
  import { ref } from "vue";

  import LayeredGraph from "@/components/organisms/LayeredGraph/LayeredGraph.vue";
  import { themeBehaviorSubject } from "@/entities/tech";
  import { useApi } from "@/lib/api-client";
  import { formatNumber } from "@/lib/format";

  const route = useRoute();
  const variantId = String(route.params.id);
  const api = useApi();
  const theme = themeBehaviorSubject.useSubscribe();

  const { data: variant, error: variantError } = await useAsyncData(
    `variant:${variantId}`,
    () => api.graphs.get(variantId),
  );
  const { data: nodes, error: nodesError } = await useAsyncData(
    `nodes:${variantId}`,
    () => api.graphs.listNodes(variantId),
  );
  const { data: edges, error: edgesError } = await useAsyncData(
    `edges:${variantId}`,
    () => api.graphs.listEdges(variantId),
  );

  const selectedNodes = ref<id[]>([]);
  const selectedLink = ref<id | null>(null);

  const error = variantError.value || nodesError.value || edgesError.value;
</script>

<template>
  <div :class="$style.page">
    <header :class="$style.header" v-if="variant">
      <div>
        <NuxtLink to="/corpora" :class="$style.back">← К списку корпусов</NuxtLink>
        <h1 :class="$style.title">{{ variant.name }}</h1>
        <p :class="$style.muted">
          builder: <code>{{ variant.builder }}</code> · cleaners:
          <code>{{ variant.cleaner_chain.join(" → ") || "—" }}</code> · clusterer:
          <code>{{ variant.clusterer ?? "—" }}</code>
        </p>
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

    <div v-else-if="nodes && edges" :class="$style.canvas">
      <LayeredGraph
        :nodes="nodes"
        :edges="edges"
        :theme="theme"
        v-model:selectedNodes="selectedNodes"
        v-model:selectedLink="selectedLink"
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
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: var(--gr-space-md);
    padding: var(--gr-space-md) var(--gr-space-xl);
    border-bottom: 1px solid var(--ksd-border-color);
    flex-shrink: 0;
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

  .canvas {
    flex: 1;
    overflow: hidden;
  }

  .error {
    padding: var(--gr-space-xl);
    color: var(--gr-status-failed);
  }
</style>
