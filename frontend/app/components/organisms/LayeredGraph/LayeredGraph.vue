<script setup lang="ts">
  import type { ThemeName } from "@krainovsd/vue-ui";
  import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

  import CityGraph from "@/components/organisms/CityGraph/CityGraph.vue";
  import type { ICityGraph } from "@/components/organisms/CityGraph/city-graph.types";
  import type { ICityGraphLink, ICityGraphNode } from "@/entities/cities";
  import type { Edge, Layer, Node } from "@/entities/api";

  import {
    ACTIVE_ALPHA,
    LAYER_COLORS,
    LAYER_ORDER,
    alphaFor,
    colorForLayer,
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

  const hotkeyEnabled = ref(true);

  // Map domain Node/Edge → @krainovsd/graph CityGraph shape, with each
  // node's data.color carrying the alpha-baked layer color. The package
  // doesn't expose a per-node opacity hook, so this is the cleanest
  // route until we PR `data.opacity` upstream.
  const cityGraph = computed<ICityGraph>(() => {
    const layerById = new Map<id, Layer>();
    for (const n of props.nodes) {
      layerById.set(n.id, n.layer);
    }

    const cityNodes: ICityGraphNode[] = props.nodes.map((n) => {
      const baseColor = colorForLayer(
        n.layer,
        typeof n.attributes?.color === "string"
          ? (n.attributes.color as string)
          : null,
      );
      const alpha = alphaFor(n.layer, activeLayer.value);
      return {
        id: n.id,
        data: {
          texts: [
            { id: 0, text: n.name },
            ...(n.summary ? [{ id: 1, text: n.summary }] : []),
          ],
          color: withAlpha(baseColor, alpha),
          size: layerSize(n.layer),
        },
      } as ICityGraphNode;
    });

    const cityLinks: ICityGraphLink[] = props.edges.map((e, i) => {
      const sourceLayer = layerById.get(e.source_node_id);
      const targetLayer = layerById.get(e.target_node_id);
      // An edge is "muted" if either endpoint is on a non-active layer.
      const minAlpha = activeLayer.value
        ? Math.min(
            sourceLayer ? alphaFor(sourceLayer, activeLayer.value) : ACTIVE_ALPHA,
            targetLayer ? alphaFor(targetLayer, activeLayer.value) : ACTIVE_ALPHA,
          )
        : ACTIVE_ALPHA;
      return {
        id: e.id,
        source: e.source_node_id,
        target: e.target_node_id,
        data: {
          id: i,
          color: withAlpha("#888888", Math.max(minAlpha * 0.6, 0.05)),
          explanation: e.explanation ?? e.relation ?? "",
        },
      } as ICityGraphLink;
    });

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

  // ---- hotkeys (1/2/3/4 = focus layer, Tab = cycle, 0/Esc = clear) ----

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
      activeLayer.value = null;
      e.preventDefault();
    }
  }

  onMounted(() => {
    window.addEventListener("keydown", onKeydown);
  });
  onBeforeUnmount(() => {
    window.removeEventListener("keydown", onKeydown);
  });

  // Also watch theme just to enforce a re-render of the inner CityGraph
  // when the user switches dark/light, since alpha-baked colors look
  // different on different backgrounds.
  watch(
    () => props.theme,
    () => {
      // Vue's reactivity already triggers re-render via cityGraph's
      // computed dependency on activeLayer + nodes; this watcher exists
      // as a hook for theme-specific overrides we'll add in 6.10.
    },
  );
</script>

<template>
  <div :class="$style.host">
    <header :class="$style.toolbar" aria-label="Layered Graph controls">
      <span :class="$style.label">Active layer:</span>
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
        :class:disabled="activeLayer === null"
        title="hotkey 0/Esc — show all"
        @click="activeLayer = null"
      >
        all
      </button>
      <span :class="$style.hint">hotkeys: 1/2/3/4 layer · Tab cycle · 0/Esc all</span>
    </header>

    <div :class="$style.canvas">
      <CityGraph
        :graph="cityGraph"
        :theme="props.theme"
        v-model:selectedNodes="selectedNodes"
        v-model:selectedLink="selectedLink"
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
    border: 2px solid;
    border-radius: var(--gr-radius-sm);
    background: transparent;
    cursor: pointer;
    font-size: 0.875rem;
    font-weight: 500;
    text-transform: lowercase;
    transition: all 0.15s ease;
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
