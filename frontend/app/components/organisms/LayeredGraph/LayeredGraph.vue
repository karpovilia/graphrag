<script setup lang="ts">
  import type { ThemeName } from "@krainovsd/vue-ui";
  import {
    computed,
    onBeforeUnmount,
    onMounted,
    ref,
    useTemplateRef,
    watch,
  } from "vue";
  import { useI18n } from "vue-i18n";

  import CityGraph from "@/components/organisms/CityGraph/CityGraph.vue";
  import type { ICityGraph } from "@/components/organisms/CityGraph/city-graph.types";
  import type { ICityGraphLink, ICityGraphNode } from "@/entities/cities";
  import type { Edge, Layer, Node } from "@/entities/api";
  import { useApi } from "@/lib/api-client";

  import LayerMap from "./LayerMap.vue";

  // Matches community-node names that were never summarised: clusterer
  // placeholder labels like "leiden #4", "Community 12", "louvain 7".
  const UNNAMED_COMMUNITY_RE = /^\s*(leiden|louvain|bayan|community)\s*#?\s*\d+\s*$/i;
  import {
    ACTIVE_ALPHA,
    LAYER_COLORS,
    LAYER_ORDER,
    colorForCommunity,
    colorForLayer,
    combineAlpha,
    resolveAlpha,
  } from "./lib/alpha";
  import { resolveDelta, type DeltaSource, type DeltaState } from "./lib/delta";

  type Props = {
    nodes: Node[];
    edges: Edge[];
    theme: ThemeName;
    /** When set, LayeredGraph fetches a cached force-layout on mount and
     * persists positions back on simulation-end / drag-end / unmount.
     * Skipping the prop turns the cache off (e.g. preview screens). */
    variantId?: id;
    /** Optional: node ids to render with a highlight halo. Used by the
     * suggestions sidebar to point the user at the pair under hover. */
    highlightedNodeIds?: id[];
    /** §0 delta overlay: id (node OR edge) → DeltaState. When present the
     * compositor folds the §0 grammar (color / alpha / strike / glow /
     * lift) on top of the layer-focus result. Owned by the host page so
     * split-view panes can sync. */
    deltaIndex?: Map<string, DeltaState> | null;
    /** Legend label only — which axis produced `deltaIndex`. The grammar
     * itself does not branch on this. */
    deltaSource?: DeltaSource;
  };

  const props = withDefaults(defineProps<Props>(), {
    variantId: undefined,
    highlightedNodeIds: () => [],
    deltaIndex: null,
    deltaSource: null,
  });
  const api = useApi();
  const { t } = useI18n();

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

  // Fine-grained filters lifted to the host page so LayersPanel and the
  // canvas stay in sync. typeFilter: "" = no filter, else nodes must
  // match Node.type exactly. hideUnnamedCommunities drops community-layer
  // nodes whose name still looks like a clusterer placeholder
  // ("leiden #4", "Community 12") and which never received a summary.
  // Multi-select entity-type filter: [] = all types, else keep only these.
  const typeFilter = defineModel<string[]>("typeFilter", { default: () => [] });
  const hideUnnamedCommunities = defineModel<boolean>(
    "hideUnnamedCommunities",
    { default: true },
  );

  const layerMapOpen = ref(false);
  const hotkeyEnabled = ref(true);
  const cityGraphRef = useTemplateRef<{
    recenter: () => void;
    collectPositions: () => Record<string, [number, number]> | null;
  }>("cityGraphRef");

  // ---- cached layout (force-directed positions) ----
  //
  // First-time visit: skipping the cache means the d3-force simulation
  // starts from random positions and takes several seconds to converge
  // on a 1.5k-node graph. We block CityGraph mount on the GET so the
  // controller can seed `node.x/y` at construction time — re-mounting
  // mid-flight would mean an already-jiggling simulation.
  const initialPositions = ref<Record<string, [number, number]> | null>(null);
  const layoutReady = ref(props.variantId === undefined);
  let saveTimer: ReturnType<typeof setTimeout> | null = null;
  let lastSaved = "";
  let pendingPositions: Record<string, [number, number]> | null = null;

  async function loadLayout() {
    if (!props.variantId) return;
    try {
      const cached = await api.graphs.getLayout(String(props.variantId));
      initialPositions.value = cached.positions ?? {};
    } catch {
      // Cache fetch is best-effort — surface no UI error, just fall
      // through to a from-scratch simulation.
      initialPositions.value = {};
    } finally {
      layoutReady.value = true;
    }
  }

  function scheduleSave() {
    if (!props.variantId) return;
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      saveTimer = null;
      flushSave();
    }, 1500);
  }

  async function flushSave() {
    if (!props.variantId) return;
    if (saveTimer) {
      clearTimeout(saveTimer);
      saveTimer = null;
    }
    const positions =
      pendingPositions ?? cityGraphRef.value?.collectPositions();
    pendingPositions = null;
    if (!positions || Object.keys(positions).length === 0) return;
    const sig = signature(positions);
    if (sig === lastSaved) return;
    lastSaved = sig;
    try {
      await api.graphs.putLayout(String(props.variantId), positions);
    } catch {
      // Best-effort — on next trigger we'll try again.
      lastSaved = "";
    }
  }

  function onLayoutChanged(positions: Record<string, [number, number]>) {
    pendingPositions = positions;
    scheduleSave();
  }

  function signature(positions: Record<string, [number, number]>): string {
    // Cheap diff: count + rounded centroid. Avoids saving an identical
    // snapshot twice in a row.
    let sx = 0;
    let sy = 0;
    let n = 0;
    for (const [x, y] of Object.values(positions)) {
      sx += x;
      sy += y;
      n += 1;
    }
    if (n === 0) return "0";
    return `${n}:${Math.round(sx / n)}:${Math.round(sy / n)}`;
  }

  function recenterGraph() {
    cityGraphRef.value?.recenter();
  }

  // entity_id → its parent community node id, derived once from
  // MEMBER_OF edges. Used by the community-map color overlay when the
  // user focuses the community layer: each entity inherits its
  // community's palette colour so the structure becomes legible.
  const entityToCommunity = computed<Map<id, id>>(() => {
    const out = new Map<id, id>();
    const layerById = new Map<id, Layer>();
    for (const n of props.nodes) layerById.set(n.id, n.layer);
    for (const e of props.edges) {
      if (e.type !== "member_of") continue;
      // MEMBER_OF orientation: source = entity, target = community.
      // Skip any edge that doesn't match — guards against ad-hoc data.
      if (
        layerById.get(e.source_node_id) === "entity" &&
        layerById.get(e.target_node_id) === "community"
      ) {
        out.set(e.source_node_id, e.target_node_id);
      }
    }
    return out;
  });

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

    const highlightSet = new Set(props.highlightedNodeIds.map(String));
    // Community-map overlay only kicks in while the user has the
    // community layer focused — outside that, defaults to layer colors.
    const communityMode = activeLayer.value === "community";
    const e2c = entityToCommunity.value;

    const deltaIndex = props.deltaIndex;

    const tf = typeFilter.value;
    const hideUnnamed = hideUnnamedCommunities.value;

    const cityNodes: ICityGraphNode[] = [];
    for (const n of nodesSorted) {
      if (tf.length && !tf.includes(n.type)) continue;
      if (
        hideUnnamed
        && n.layer === "community"
        && !n.summary
        && UNNAMED_COMMUNITY_RE.test(String(n.name ?? ""))
      ) {
        continue;
      }
      const layerAlpha = resolveAlpha(
        n.layer,
        activeLayer.value,
        perLayerAlpha.value,
        sliceMode.value,
      );
      if (layerAlpha === 0) continue; // sliceMode hides; don't bother rendering
      let baseColor = colorForLayer(
        n.layer,
        typeof n.attributes?.color === "string"
          ? (n.attributes.color as string)
          : null,
      );
      if (communityMode) {
        if (n.layer === "community") {
          baseColor = colorForCommunity(String(n.id));
        } else if (n.layer === "entity") {
          const cid = e2c.get(n.id);
          if (cid !== undefined) baseColor = colorForCommunity(String(cid));
        }
      }

      // §0 delta fold — overrides come AFTER layer color/alpha so the two
      // lenses compose (combineAlpha = min).
      const delta = resolveDelta(String(n.id), deltaIndex);
      const color = delta.color ?? baseColor;
      const alpha = combineAlpha(layerAlpha, delta.alpha);

      const isHighlighted = highlightSet.has(String(n.id));
      // Spotlight: when a highlight set is active (assistant "найди…",
      // sidebar hover), the matches glow at full alpha and everything else
      // dims hard — otherwise a halo on a few nodes is invisible in a dense
      // cloud. No active highlight → leave alpha as the layer/delta result.
      const spotlightActive = highlightSet.size > 0;
      const effectiveAlpha =
        spotlightActive && !isHighlighted ? Math.min(alpha, 0.08) : alpha;
      cityNodes.push({
        id: n.id,
        // top-level `name` is what @krainovsd/graph renders as the
        // canvas label by default; without it the lib falls back to the
        // UUID `id`. `data.texts` is consumed by custom textDraw hooks
        // (none wired yet) — keep both so a future hook can show summary too.
        name: n.name,
        highlight: isHighlighted || undefined,
        data: {
          texts: [
            { id: 0, text: n.name },
            ...(n.summary ? [{ id: 1, text: n.summary }] : []),
          ],
          // Native per-node alpha (sec0 migration) — color stays 6-digit
          // so the delta tint is animatable and the wrapper no longer
          // bakes alpha into an 8-digit hex.
          color: baseColorOrDelta(color),
          alpha: effectiveAlpha,
          size: layerSize(n.layer),
          strike: delta.strike || undefined,
          // The visible halo is drawn from `data.glow` (get-node-options
          // nodeExtraDraw) — drive it from the highlight set too, not just
          // born/evidence deltas, so search/sidebar highlights actually show.
          glow: delta.glow || isHighlighted || undefined,
          deltaState: delta.state,
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
      const delta = resolveDelta(String(e.id), deltaIndex);
      // Edge fill follows delta when set (evidence keeps base grey at full
      // alpha; dead/invalidated grey + strike), else the neutral edge grey.
      const baseLinkAlpha = Math.max(linkAlpha * 0.6, 0.05);
      const alpha =
        delta.state === null
          ? baseLinkAlpha
          : combineAlpha(baseLinkAlpha, delta.alpha);
      cityLinks.push({
        id: e.id,
        source: e.source_node_id,
        target: e.target_node_id,
        data: {
          id: i,
          // Higher-order (2nd-order) DERIVED projection edges get a distinct
          // violet so they read apart from builder edges; an explicit
          // attributes.color (e.g. two layer-pair projections shown at once,
          // each its own colour) wins; delta overrides win over all.
          color:
            delta.color ??
            (typeof e.attributes?.color === "string"
              ? (e.attributes.color as string)
              : e.type === "derived"
                ? "#9467bd"
                : "#888888"),
          alpha,
          // Projection / derived edges drawn thicker so the overlay reads.
          width: e.type === "derived" ? 0.35 : undefined,
          strike: delta.strike || undefined,
          explanation: e.explanation ?? e.relation ?? "",
        },
      } as ICityGraphLink);
    }

    return { nodes: cityNodes, links: cityLinks };
  });

  // Pass-through: kept as a named helper so the node loop reads cleanly
  // and a future theme-aware tint can hook here.
  function baseColorOrDelta(color: string): string {
    return color;
  }

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
    } else if (e.key === "f" || e.key === "F") {
      recenterGraph();
      e.preventDefault();
    }
  }

  onMounted(() => {
    window.addEventListener("keydown", onKeydown);
    loadLayout();
  });
  onBeforeUnmount(() => {
    window.removeEventListener("keydown", onKeydown);
    // Flush any pending debounce + grab one last snapshot of the
    // current canvas — this is the third save trigger.
    void flushSave();
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
      <span :class="$style.label">{{ t("graph.layerLabel") }}</span>
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
        {{ t("graph.showAll") }}
      </button>
      <button
        type="button"
        :class="[$style.chip, layerMapOpen ? $style.chip_active : '']"
        title="hotkey L — Layer Map"
        @click="layerMapOpen = !layerMapOpen"
      >
        {{ t("graph.layerMap") }}
      </button>
      <button
        type="button"
        :class="$style.chip"
        title="hotkey F — recenter graph"
        @click="recenterGraph"
      >
        {{ t("graph.recenter") }}
      </button>
      <button
        v-for="tp in typeFilter"
        :key="tp"
        type="button"
        :class="[$style.chip, $style.chip_filter]"
        :title="t('graph.clearFilter')"
        @click="typeFilter = typeFilter.filter((x) => x !== tp)"
      >
        {{ t("graph.typeFilter", { type: tp }) }} ×
      </button>
      <button
        v-if="!hideUnnamedCommunities"
        type="button"
        :class="[$style.chip, $style.chip_filter]"
        @click="hideUnnamedCommunities = true"
      >
        {{ t("graph.showCommunities") }} ✓
      </button>
      <span :class="$style.hint">{{ t("graph.hotkeyHint") }}</span>
    </header>

    <div :class="$style.canvas">
      <CityGraph
        v-if="layoutReady"
        ref="cityGraphRef"
        :graph="cityGraph"
        :theme="props.theme"
        :initial-positions="initialPositions ?? undefined"
        v-model:selectedNodes="selectedNodes"
        v-model:selectedLink="selectedLink"
        @layout-changed="onLayoutChanged"
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

  .chip_filter {
    border-color: var(--ksd-accent-color);
    color: var(--ksd-accent-color);
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
