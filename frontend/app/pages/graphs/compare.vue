<script setup lang="ts">
  import { useAsyncData } from "nuxt/app";
  import { computed, ref } from "vue";
  import { useRoute } from "vue-router";
  import { useI18n } from "vue-i18n";

  import LayeredGraph from "@/components/organisms/LayeredGraph/LayeredGraph.vue";
  import { themeBehaviorSubject } from "@/entities/tech";
  import { useApi } from "@/lib/api-client";
  import type { Layer } from "@/entities/api";
  import { LAYER_ORDER } from "@/components/organisms/LayeredGraph/lib/alpha";
  import { formatNumber } from "@/lib/format";

  const { t } = useI18n();

  // Phase 6.8 — split-view MoE comparison. Two LayeredGraphs side by
  // side; activeLayer + visualOrder + perLayerAlpha + sliceMode are
  // synced so the user toggles the layer focus once and both panes
  // mirror. Selection is sync'd by canonical_id (same real-world
  // entity surfaced across variants).

  const route = useRoute();
  const api = useApi();
  const theme = themeBehaviorSubject.useSubscribe();

  const ids = computed<string[]>(() => {
    const raw = route.query.ids;
    const list = Array.isArray(raw)
      ? raw.filter((v): v is string => Boolean(v))
      : raw
        ? String(raw).split(",")
        : [];
    return list.filter((s) => Boolean(s)).slice(0, 2);
  });

  const left = computed(() => ids.value[0]);
  const right = computed(() => ids.value[1]);

  const { data: leftVariant } = await useAsyncData(
    () => `variant-cmp:${left.value}`,
    () => api.graphs.get(left.value as string),
    { watch: [left] },
  );
  const { data: rightVariant } = await useAsyncData(
    () => `variant-cmp:${right.value}`,
    () => api.graphs.get(right.value as string),
    { watch: [right] },
  );
  const { data: leftNodes } = await useAsyncData(
    () => `cmp-nodes:${left.value}`,
    () => api.graphs.listNodes(left.value as string),
    { watch: [left] },
  );
  const { data: leftEdges } = await useAsyncData(
    () => `cmp-edges:${left.value}`,
    () => api.graphs.listEdges(left.value as string),
    { watch: [left] },
  );
  const { data: rightNodes } = await useAsyncData(
    () => `cmp-nodes:${right.value}`,
    () => api.graphs.listNodes(right.value as string),
    { watch: [right] },
  );
  const { data: rightEdges } = await useAsyncData(
    () => `cmp-edges:${right.value}`,
    () => api.graphs.listEdges(right.value as string),
    { watch: [right] },
  );

  // Synced state
  const activeLayer = ref<Layer | null>(null);
  const visualOrder = ref<Layer[]>([...LAYER_ORDER]);
  const perLayerAlpha = ref<Partial<Record<Layer, number>>>({});
  const sliceMode = ref(false);

  // Selection: each pane has its own selectedNodes (local id), but we
  // also propagate by canonical_id so a click on the left panel
  // highlights the matching node on the right.
  const leftSelected = ref<id[]>([]);
  const rightSelected = ref<id[]>([]);
  const leftLink = ref<id | null>(null);
  const rightLink = ref<id | null>(null);

  function syncFromLeft(ids: id[]) {
    leftSelected.value = ids;
    if (!ids.length) {
      rightSelected.value = [];
      return;
    }
    const canonicals = new Set<string>();
    for (const nid of ids) {
      const n = (leftNodes.value ?? []).find((x) => x.id === nid);
      if (n?.canonical_id) canonicals.add(n.canonical_id);
    }
    rightSelected.value = (rightNodes.value ?? [])
      .filter((n) => n.canonical_id && canonicals.has(n.canonical_id))
      .map((n) => n.id);
  }

  function syncFromRight(ids: id[]) {
    rightSelected.value = ids;
    if (!ids.length) {
      leftSelected.value = [];
      return;
    }
    const canonicals = new Set<string>();
    for (const nid of ids) {
      const n = (rightNodes.value ?? []).find((x) => x.id === nid);
      if (n?.canonical_id) canonicals.add(n.canonical_id);
    }
    leftSelected.value = (leftNodes.value ?? [])
      .filter((n) => n.canonical_id && canonicals.has(n.canonical_id))
      .map((n) => n.id);
  }
</script>

<template>
  <div :class="$style.page">
    <header :class="$style.header">
      <NuxtLink to="/corpora" :class="$style.back">{{ t("graph.backToCorpora") }}</NuxtLink>
      <h1 :class="$style.title">{{ t("compare.title") }}</h1>
      <p :class="$style.muted" v-if="ids.length < 2">
        {{ t("compare.hint") }} <code>?ids=v1,v2</code>.
      </p>
    </header>

    <div :class="$style.split" v-if="ids.length === 2">
      <section :class="$style.pane">
        <header :class="$style.paneHeader" v-if="leftVariant">
          <strong>{{ leftVariant.name }}</strong>
          <span :class="$style.muted">
            {{ leftVariant.builder }} · {{ formatNumber(leftVariant.node_count) }}n
            · v{{ leftVariant.version }}
          </span>
        </header>
        <LayeredGraph
          v-if="leftNodes && leftEdges"
          :nodes="leftNodes"
          :edges="leftEdges"
          :theme="theme"
          v-model:active-layer="activeLayer"
          v-model:visual-order="visualOrder"
          v-model:per-layer-alpha="perLayerAlpha"
          v-model:slice-mode="sliceMode"
          v-model:selectedNodes="leftSelected"
          v-model:selectedLink="leftLink"
          @update:selected-nodes="syncFromLeft"
        />
      </section>

      <section :class="$style.pane">
        <header :class="$style.paneHeader" v-if="rightVariant">
          <strong>{{ rightVariant.name }}</strong>
          <span :class="$style.muted">
            {{ rightVariant.builder }} · {{ formatNumber(rightVariant.node_count) }}n
            · v{{ rightVariant.version }}
          </span>
        </header>
        <LayeredGraph
          v-if="rightNodes && rightEdges"
          :nodes="rightNodes"
          :edges="rightEdges"
          :theme="theme"
          v-model:active-layer="activeLayer"
          v-model:visual-order="visualOrder"
          v-model:per-layer-alpha="perLayerAlpha"
          v-model:slice-mode="sliceMode"
          v-model:selectedNodes="rightSelected"
          v-model:selectedLink="rightLink"
          @update:selected-nodes="syncFromRight"
        />
      </section>
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
    font-size: 1.4rem;
    font-weight: 700;
  }

  .muted {
    color: var(--ksd-text-secondary-color);
    font-size: 0.875rem;
  }

  .split {
    flex: 1;
    display: grid;
    grid-template-columns: 1fr 1fr;
    overflow: hidden;
  }

  .pane {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border-right: 1px solid var(--ksd-border-color);

    &:last-child {
      border-right: none;
    }
  }

  .paneHeader {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: var(--gr-space-xs) var(--gr-space-md);
    background: var(--ksd-card-bg-color);
    border-bottom: 1px solid var(--ksd-border-color);
    flex-shrink: 0;
  }
</style>
