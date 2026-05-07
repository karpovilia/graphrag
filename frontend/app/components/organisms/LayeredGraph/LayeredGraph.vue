<script setup lang="ts">
  import type { ThemeName } from "@krainovsd/vue-ui";
  import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

  import CityGraph from "@/components/organisms/CityGraph/CityGraph.vue";
  import type { ICityGraph } from "@/components/organisms/CityGraph/city-graph.types";
  import type { ICityGraphLink, ICityGraphNode } from "@/entities/cities";
  import type { Edge, Layer, Node } from "@/entities/api";

  import LayerMap from "./LayerMap.vue";
  import {
    ACTIVE_ALPHA,
    LAYER_COLORS,
    LAYER_ORDER,
    colorForLayer,
    resolveAlpha,
    withAlpha,
  } from "./lib/alpha";

  type Props = {
    nodes: Node[];
    edges: Edge[];
    theme: ThemeName;
  };

  const props = defineProps<Props>();

  const activeLayer = defineModel<Layer | null>("activeLayer", {
    default: null,
  });
  const selectedNodes = defineModel<id[]>("selectedNodes", { default: [] });
  const selectedLink = defineModel<id | null>("selectedLink", { default: null });

  // Layer Map state — surfaced as `defineModel`s so a host page can
  // sync them across multiple LayeredGraph instances (Phase 6.8 split-view).
  const visualOrder = defineModel<Layer[]>("visualOrder", {
    default: () => [...LAYER_ORDER],
  });
  const perLayerAlpha = defineModel<Partial<Record<Layer, number>>>(
    "perLayerAlpha",
    { default: () => ({}) },
  );
  const sliceMode = defineModel<boolean>("sliceMode", { default: false });

  const layerMapOpen = ref(false);
  const hotkeyEnabled = ref(true);

  // Map domain Node/Edge → @krainovsd/graph CityGraph shape, with each
  // node's data.color carrying the resolved alpha. The package doesn't
  // expose a per-node opacity hook, so this is the cleanest route until
  // we PR `data.opacity` upstream.
  const cityGraph = computed<ICityGraph>(() => {
    const layerById = new Map<id, Layer>();
    for (const n of props.nodes) layerById.set(n.id, n.layer);

    const orderRank = new Map<Layer, number>();
    visualOrder.value.forEach((layer, i) => orderRank.set(layer, i));
    const rankOf = (layer: Layer) => orderRank.get(layer) ?? 99;

    const nodesSorted = [...props.nodes].sort(
      (a, b) => rankOf(a.layer) - rankOf(b.layer),
    );

    const cityNodes: ICityGraphNode[] = [];
    for (const n of nodesSorted) {
      const alpha = resolveAlpha(
        n.layer,
        activeLayer.value,
        perLayerAlpha.value,
        sliceMode.value,
      );
      if (alpha === 0) continue; // sliceMode hides; don't bother rendering
      const baseColor = colorForLayer(
        n.layer,
        typeof n.attributes?.color === "string"
          ? (n.attributes.color as string)
          : null,
      );
      cityNodes.push({
        id: n.id,
        data: {
          texts: [
            { id: 0, text: n.name },
            ...(n.summary ? [{ id: 1, text: n.summary }] : []),
          ],
          color: withAlpha(baseColor, alpha),
          size: layerSize(n.layer),
        },
      } as ICityGraphNode);
    }

    const visibleIds = new Set(cityNodes.map((n) => n.id));

    const cityLinks: ICityGraphLink[] = [];
    for (const [i, e] of props.edges.entries()) {
      if (!visibleIds.has(e.source_node_id) || !visibleIds.has(e.target_node_id)) {
        continue;
      }
      const sourceLayer = layerById.get(e.source_node_id);
      const targetLayer = layerById.get(e.target_node_id);
      const linkAlpha = Math.min(
        sourceLayer
          ? resolveAlpha(
              sourceLayer,
              activeLayer.value,
              perLayerAlpha.value,
              sliceMode.value,
            )
          : ACTIVE_ALPHA,
        targetLayer
          ? resolveAlpha(
              targetLayer,
              activeLayer.value,
              perLayerAlpha.value,
              sliceMode.value,
            )
          : ACTIVE_ALPHA,
      );
      cityLinks.push({
        id: e.id,
        source: e.source_node_id,
        target: e.target_node_id,
        data: {
          id: i,
          color: withAlpha("#888888", Math.max(linkAlpha * 0.6, 0.05)),
          explanation: e.explanation ?? e.relation ?? "",
        },
      } as ICityGraphLink);
    }

    return { nodes: cityNodes, links: cityLinks };
  });

  function layerSize(layer: Layer): number {
    const order: Record<Layer, number> = {
      chunk: 0,
      entity: 1,
      community: 2,
      topic: 3,
    };
    return order[layer] ?? 0;
  }

  // ---- hotkeys (1/2/3/4 focus, Tab cycle, 0/Esc clear, L overlay) ----

  function onKeydown(e: KeyboardEvent) {
    if (!hotkeyEnabled.value) return;
    const target = e.target as HTMLElement | null;
    if (target && ["INPUT", "TEXTAREA"].includes(target.tagName)) return;

    if (e.key >= "1" && e.key <= "4") {
      const idx = Number(e.key) - 1;
      if (idx < LAYER_ORDER.length) {
        activeLayer.value = LAYER_ORDER[idx] ?? null;
        e.preventDefault();
      }
    } else if (e.key === "Tab") {
      const current = activeLayer.value;
      const idx = current ? LAYER_ORDER.indexOf(current) : -1;
      const nextIdx = (idx + 1) % LAYER_ORDER.length;
      activeLayer.value = LAYER_ORDER[nextIdx] ?? null;
      e.preventDefault();
    } else if (e.key === "0" || e.key === "Escape") {
      if (layerMapOpen.value) {
        layerMapOpen.value = false;
      } else {
        activeLayer.value = null;
      }
      e.preventDefault();
    } else if (e.key === "l" || e.key === "L") {
      layerMapOpen.value = !layerMapOpen.value;
      e.preventDefault();
    }
  }

  onMounted(() => {
    window.addEventListener("keydown", onKeydown);
  });
  onBeforeUnmount(() => {
    window.removeEventListener("keydown", onKeydown);
  });

  function resetLayerMap() {
    visualOrder.value = [...LAYER_ORDER];
    perLayerAlpha.value = {};
    sliceMode.value = false;
  }

  watch(
    () => props.theme,
    () => {
      // Hook for theme-specific overrides; alpha-baked colors are
      // recomputed automatically through the cityGraph computed.
    },
  );
</script>

<template>
  <div :class="$style.host">
    <header :class="$style.toolbar" aria-label="Layered Graph controls">
      <span :class="$style.label">Layer:</span>
      <button
        v-for="(layer, i) in LAYER_ORDER"
        :key="layer"
        type="button"
        :class="[
          $style.chip,
          activeLayer === layer ? $style.chip_active : '',
        ]"
        :style="{
          borderColor: LAYER_COLORS[layer],
          color: activeLayer === layer ? 'white' : LAYER_COLORS[layer],
          background: activeLayer === layer ? LAYER_COLORS[layer] : 'transparent',
        }"
        :title="`hotkey ${i + 1}`"
        @click="activeLayer = layer"
      >
        {{ layer }}
      </button>
      <button
        type="button"
        :class="$style.chip"
        title="hotkey 0/Esc — show all"
        @click="activeLayer = null"
      >
        all
      </button>
      <button
        type="button"
        :class="[$style.chip, layerMapOpen ? $style.chip_active : '']"
        title="hotkey L — Layer Map"
        @click="layerMapOpen = !layerMapOpen"
      >
        layer map
      </button>
      <span :class="$style.hint">
        hotkeys: 1/2/3/4 · Tab · L · 0/Esc
      </span>
    </header>

    <div :class="$style.canvas">
      <CityGraph
        :graph="cityGraph"
        :theme="props.theme"
        v-model:selectedNodes="selectedNodes"
        v-model:selectedLink="selectedLink"
      />

      <LayerMap
        v-if="layerMapOpen"
        :active-layer="activeLayer"
        :visual-order="visualOrder"
        :per-layer-alpha="perLayerAlpha"
        :slice-mode="sliceMode"
        @close="layerMapOpen = false"
        @update:active-layer="activeLayer = $event"
        @update:visual-order="visualOrder = $event"
        @update:per-layer-alpha="perLayerAlpha = $event"
        @update:slice-mode="sliceMode = $event"
        @reset="resetLayerMap"
      />
    </div>
  </div>
</template>

<style lang="scss" module>
  .host {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    position: relative;
  }

  .toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--gr-space-xs);
    padding: var(--gr-space-xs) var(--gr-space-md);
    background: var(--ksd-card-bg-color);
    border-bottom: 1px solid var(--ksd-border-color);
    flex-shrink: 0;
  }

  .label {
    font-size: 0.875rem;
    font-weight: 500;
    color: var(--ksd-text-secondary-color);
  }

  .chip {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border: 2px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    cursor: pointer;
    font-size: 0.875rem;
    font-weight: 500;
    text-transform: lowercase;
    transition: all 0.15s ease;
    color: var(--ksd-text-main-color);
  }

  .chip_active {
    box-shadow: 0 0 0 2px var(--ksd-accent-color);
  }

  .hint {
    margin-left: auto;
    font-size: 0.75rem;
    color: var(--ksd-text-secondary-color);
  }

  .canvas {
    flex: 1;
    position: relative;
  }
</style>
