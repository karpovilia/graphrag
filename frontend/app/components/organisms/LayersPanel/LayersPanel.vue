<script setup lang="ts">
  import { computed, ref } from "vue";
  import { useI18n } from "vue-i18n";

  import type { Edge, Layer, Node } from "@/entities/api";
  import { LAYER_COLORS, LAYER_ORDER } from "@/components/organisms/LayeredGraph/lib/alpha";

  type Props = {
    nodes: Node[];
    edges: Edge[];
  };

  const props = defineProps<Props>();
  const emit = defineEmits<{
    (e: "close"): void;
    (e: "select-node", id: string): void;
  }>();

  const { t } = useI18n();

  const activeLayer = ref<Layer | "all">("all");
  // Lifted to the parent so the canvas (LayeredGraph) and this table
  // stay in sync — picking PERSON here filters the graph too.
  // Multi-select entity-type filter (lifted to the page → also filters the
  // canvas): [] = all, else keep nodes whose type is in the set. Toggle types
  // as chips to show, e.g., people AND organisations at once.
  const typeFilter = defineModel<string[]>("typeFilter", { default: () => [] });
  function toggleType(tp: string) {
    typeFilter.value = typeFilter.value.includes(tp)
      ? typeFilter.value.filter((x) => x !== tp)
      : [...typeFilter.value, tp];
  }
  const hideUnnamedCommunities = defineModel<boolean>(
    "hideUnnamedCommunities",
    { default: true },
  );
  const search = ref<string>("");

  // Outgoing-degree per node (incoming + outgoing summed via the
  // undirected adjacency we already built for the merge agent UX).
  const degrees = computed(() => {
    const d = new Map<string, number>();
    for (const e of props.edges) {
      d.set(String(e.source_node_id), (d.get(String(e.source_node_id)) ?? 0) + 1);
      d.set(String(e.target_node_id), (d.get(String(e.target_node_id)) ?? 0) + 1);
    }
    return d;
  });

  type LayerStat = {
    layer: Layer;
    count: number;
    types: { type: string; count: number }[];
  };

  const layerStats = computed<LayerStat[]>(() => {
    const buckets = new Map<Layer, Node[]>();
    for (const layer of LAYER_ORDER) buckets.set(layer, []);
    for (const n of props.nodes) {
      const arr = buckets.get(n.layer);
      if (arr) arr.push(n);
    }
    return LAYER_ORDER.map((layer) => {
      const list = buckets.get(layer) ?? [];
      const typeCounts = new Map<string, number>();
      for (const n of list) {
        typeCounts.set(n.type, (typeCounts.get(n.type) ?? 0) + 1);
      }
      const types = [...typeCounts.entries()]
        .map(([type, count]) => ({ type, count }))
        .sort((a, b) => b.count - a.count);
      return { layer, count: list.length, types };
    });
  });

  const totalCount = computed(() => props.nodes.length);

  const visibleNodes = computed<Node[]>(() => {
    const q = search.value.trim().toLowerCase();
    const tFilter = typeFilter.value;
    const layerFilter = activeLayer.value;
    return props.nodes
      .filter((n) => (layerFilter === "all" ? true : n.layer === layerFilter))
      .filter((n) => (tFilter.length ? tFilter.includes(n.type) : true))
      .filter((n) => (q ? (n.name ?? "").toLowerCase().includes(q) : true))
      .sort((a, b) => {
        const da = degrees.value.get(String(a.id)) ?? 0;
        const db = degrees.value.get(String(b.id)) ?? 0;
        return db - da;
      })
      .slice(0, 200);
  });

  const typesForActiveLayer = computed(() => {
    if (activeLayer.value === "all") {
      const acc = new Map<string, number>();
      for (const s of layerStats.value)
        for (const tt of s.types)
          acc.set(tt.type, (acc.get(tt.type) ?? 0) + tt.count);
      return [...acc.entries()].map(([type, count]) => ({ type, count }))
        .sort((a, b) => b.count - a.count);
    }
    const stat = layerStats.value.find((s) => s.layer === activeLayer.value);
    return stat?.types ?? [];
  });

  function pickLayer(l: Layer | "all") {
    activeLayer.value = l;
    typeFilter.value = [];
  }
</script>

<template>
  <aside :class="$style.panel" :aria-label="t('layersPanel.aria')">
    <header :class="$style.header">
      <h2 :class="$style.title">{{ t("layersPanel.title") }}</h2>
      <button type="button" :class="$style.close" @click="emit('close')">×</button>
    </header>

    <section :class="$style.statsRow">
      <button
        type="button"
        :class="[$style.layerChip, activeLayer === 'all' ? $style.chip_active : '']"
        @click="pickLayer('all')"
      >
        {{ t("layersPanel.allLayers") }}
        <span :class="$style.muted">{{ totalCount }}</span>
      </button>
      <button
        v-for="s in layerStats"
        :key="s.layer"
        type="button"
        :class="[$style.layerChip, activeLayer === s.layer ? $style.chip_active : '']"
        :style="{ borderColor: LAYER_COLORS[s.layer] }"
        :disabled="s.count === 0"
        @click="pickLayer(s.layer)"
      >
        {{ s.layer }}
        <span :class="$style.muted">{{ s.count }}</span>
      </button>
    </section>

    <section :class="$style.controls">
      <input
        v-model="search"
        type="search"
        :placeholder="t('layersPanel.searchPlaceholder')"
        :class="$style.search"
      />
    </section>

    <section v-if="typesForActiveLayer.length > 1" :class="$style.typeBar">
      <span :class="$style.typeBarLabel">{{ t("layersPanel.types") }}</span>
      <button
        v-for="tt in typesForActiveLayer"
        :key="tt.type"
        type="button"
        :class="[$style.typeChip, typeFilter.includes(tt.type) ? $style.typeChip_on : '']"
        data-testid="type-chip"
        @click="toggleType(tt.type)"
      >
        {{ tt.type }} <span :class="$style.muted">{{ tt.count }}</span>
      </button>
      <button
        v-if="typeFilter.length"
        type="button"
        :class="$style.typeClear"
        @click="typeFilter = []"
      >
        {{ t("layersPanel.typeAll") }}
      </button>
    </section>

    <section :class="$style.controls">
      <label
        :class="$style.checkRow"
        :title="t('layersPanel.hideUnnamedCommunitiesHint')"
      >
        <input
          type="checkbox"
          v-model="hideUnnamedCommunities"
        />
        <span>{{ t("layersPanel.hideUnnamedCommunities") }}</span>
      </label>
    </section>

    <section :class="$style.tableShell">
      <table :class="$style.table">
        <thead>
          <tr>
            <th>{{ t("layersPanel.colName") }}</th>
            <th>{{ t("layersPanel.colType") }}</th>
            <th :class="$style.numCol">{{ t("layersPanel.colDegree") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="n in visibleNodes"
            :key="n.id"
            :class="$style.row"
            @click="emit('select-node', String(n.id))"
          >
            <td :class="$style.nameCell">
              <span
                :class="$style.layerSwatch"
                :style="{ background: LAYER_COLORS[n.layer] }"
              />
              <span>{{ n.name }}</span>
            </td>
            <td :class="$style.muted">{{ n.type }}</td>
            <td :class="[$style.muted, $style.numCol]">
              {{ degrees.get(String(n.id)) ?? 0 }}
            </td>
          </tr>
          <tr v-if="!visibleNodes.length">
            <td colspan="3" :class="$style.empty">
              {{ t("layersPanel.empty") }}
            </td>
          </tr>
        </tbody>
      </table>
      <p :class="$style.footnote" v-if="visibleNodes.length === 200">
        {{ t("layersPanel.truncated") }}
      </p>
    </section>
  </aside>
</template>

<style lang="scss" module>
  .panel {
    position: absolute;
    top: var(--gr-space-md);
    right: var(--gr-space-md);
    width: 420px;
    max-height: calc(100vh - var(--gr-space-md) * 2);
    background: var(--ksd-card-bg-color);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-md);
    box-shadow: var(--gr-shadow-lg);
    display: flex;
    flex-direction: column;
    z-index: 100;
  }
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--gr-space-sm) var(--gr-space-md);
    border-bottom: 1px solid var(--ksd-border-color);
  }
  .title {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
  }
  .close {
    background: transparent;
    border: none;
    color: var(--ksd-text-secondary-color);
    cursor: pointer;
    font-size: 1.25rem;
    line-height: 1;
  }
  .statsRow {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gr-space-2xs);
    padding: var(--gr-space-sm) var(--gr-space-md);
    border-bottom: 1px solid var(--ksd-border-color);
  }
  .layerChip {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    color: var(--ksd-text-main-color);
    font-size: 0.875rem;
    cursor: pointer;
    display: inline-flex;
    gap: var(--gr-space-2xs);
    align-items: center;

    &:disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }
  }
  .chip_active {
    background: var(--ksd-accent-color);
    color: white;
    border-color: var(--ksd-accent-color);
  }
  .controls {
    display: flex;
    gap: var(--gr-space-2xs);
    padding: var(--gr-space-sm) var(--gr-space-md);
    border-bottom: 1px solid var(--ksd-border-color);
  }
  .search,
  .select {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
    font-size: 0.875rem;
  }
  .search {
    flex: 1;
  }
  .typeBar {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gr-space-2xs);
    align-items: center;
    padding: var(--gr-space-sm) var(--gr-space-md);
    border-bottom: 1px solid var(--ksd-border-color);
  }
  .typeBarLabel {
    font-size: 0.75rem;
    color: var(--ksd-text-secondary-color);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .typeChip {
    padding: 2px var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    color: var(--ksd-text-main-color);
    font-size: 0.8rem;
    cursor: pointer;
    display: inline-flex;
    gap: 4px;
    align-items: center;

    &:hover {
      border-color: var(--ksd-accent-color);
    }
  }
  .typeChip_on {
    background: var(--ksd-accent-color);
    color: #fff;
    border-color: var(--ksd-accent-color);

    .muted {
      color: rgb(255 255 255 / 80%);
    }
  }
  .typeClear {
    padding: 2px var(--gr-space-xs);
    border: 1px dashed var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    color: var(--ksd-text-secondary-color);
    font-size: 0.8rem;
    cursor: pointer;
  }
  .checkRow {
    display: flex;
    align-items: center;
    gap: var(--gr-space-2xs);
    font-size: 0.875rem;
    color: var(--ksd-text-main-color);
    cursor: pointer;
    user-select: none;
  }
  .tableShell {
    overflow-y: auto;
    flex: 1;
  }
  .table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;

    th {
      text-align: left;
      padding: var(--gr-space-2xs) var(--gr-space-sm);
      color: var(--ksd-text-secondary-color);
      font-weight: 500;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      position: sticky;
      top: 0;
      background: var(--ksd-card-bg-color);
      border-bottom: 1px solid var(--ksd-border-color);
    }

    td {
      padding: var(--gr-space-2xs) var(--gr-space-sm);
      border-bottom: 1px solid var(--ksd-border-color);
    }
  }
  .row {
    cursor: pointer;

    &:hover {
      background: var(--ksd-bg-color);
    }
  }
  .nameCell {
    display: flex;
    align-items: center;
    gap: var(--gr-space-2xs);
  }
  .layerSwatch {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .muted {
    color: var(--ksd-text-secondary-color);
    font-size: 0.8rem;
  }
  .numCol {
    text-align: right;
    width: 60px;
  }
  .empty {
    text-align: center;
    color: var(--ksd-text-secondary-color);
    padding: var(--gr-space-md);
  }
  .footnote {
    margin: 0;
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    font-size: 0.75rem;
    color: var(--ksd-text-secondary-color);
    border-top: 1px solid var(--ksd-border-color);
  }
</style>
