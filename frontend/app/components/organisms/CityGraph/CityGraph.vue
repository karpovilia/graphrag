<script setup lang="ts">
  import { GraphCanvas, type ZoomEventInterface } from "@krainovsd/graph";
  import type { ThemeName } from "@krainovsd/vue-ui";
  import { computed, toRaw, useTemplateRef, watch } from "vue";
  import type {
    ICityGraphLink,
    ICityGraphLinkData,
    ICityGraphNode,
    ICityGraphNodeData,
  } from "@/entities/cities";
  import { DEFAULT_SETTINGS } from "./city-graph.constats";
  import type { ICityGraph } from "./city-graph.types";
  import { getCorrectData } from "./lib/get-correct-data";
  import { getLinkOptions } from "./lib/get-link-options";
  import { getNodeOptions } from "./lib/get-node-options";

  type Props = {
    graph: ICityGraph;
    theme: ThemeName;
    /** Cached force-layout (node id → [x, y]). When present, each node's
     * x/y is seeded so the d3-force simulation converges instantly
     * instead of running from random positions for several seconds.
     * Nodes missing from the map fall through to the lib's default
     * random init — the simulation will only have to move the new ones. */
    initialPositions?: Record<string, [number, number]>;
  };

  const props = defineProps<Props>();
  const emit = defineEmits<{
    (e: "layout-changed", positions: Record<string, [number, number]>): void;
  }>();
  const graphRef = useTemplateRef("graph");
  let graphController: GraphCanvas<ICityGraphNodeData, ICityGraphLinkData> | undefined;
  const selectedNodes = defineModel<id[]>("selectedNodes", { default: [] });
  const selectedLink = defineModel<id | null>("selectedLink", { default: null });
  const checkedGraph = computed(() => getCorrectData(props.graph.nodes, props.graph.links));

  function seedPositions<T extends { id: id; x?: number; y?: number }>(
    nodes: T[],
  ): T[] {
    const seed = props.initialPositions;
    if (!seed) return nodes;
    for (const n of nodes) {
      const p = seed[String(n.id)];
      if (p) {
        n.x = p[0];
        n.y = p[1];
      }
    }
    return nodes;
  }

  function collectPositions(): Record<string, [number, number]> | null {
    if (!graphController) return null;
    const ctrl = graphController as unknown as {
      nodes: { id: id; x?: number; y?: number }[];
    };
    const out: Record<string, [number, number]> = {};
    for (const n of ctrl.nodes) {
      if (typeof n.x === "number" && typeof n.y === "number") {
        out[String(n.id)] = [n.x, n.y];
      }
    }
    return out;
  }

  function emitPositions() {
    const positions = collectPositions();
    if (positions && Object.keys(positions).length > 0) {
      emit("layout-changed", positions);
    }
  }

  function onClick(
    event: MouseEvent | TouchEvent,
    node: ICityGraphNode | undefined,
    link: ICityGraphLink | undefined,
  ) {
    if (!graphController) return;

    if (!node && !link) {
      selectedNodes.value = [];
      selectedLink.value = null;
    }

    if (node) {
      selectedLink.value = null;
      if (event.shiftKey) {
        const nodeIndex = selectedNodes.value.findIndex((nid) => nid === node.id);

        if (nodeIndex === -1) {
          selectedNodes.value = [...selectedNodes.value, node.id];
        } else {
          selectedNodes.value = selectedNodes.value.filter((nid) => nid !== node.id);
        }
      } else {
        selectedNodes.value = [node.id];
      }
    }

    if (link) {
      selectedNodes.value = [];
      selectedLink.value = link.data?.id ?? null;
    }
  }

  /** Rescue the zoom transform ONLY when the entire graph bbox has left
   * the viewport — otherwise leave normal pan/zoom alone (zoom-to-cursor
   * relies on the lib's own (k, x, y) math; touching it mid-event makes
   * the canvas jump). Fires from d3-zoom's "zoom" handler before the
   * lib commits `areaTransform = event.transform`; mutating
   * event.transform is enough, but we also overwrite the canvas's
   * `__zoom` stash so the next wheel/drag resumes from the rescued
   * state rather than drifting further off-screen.
   *
   * Without this, strong zoom-out lets the user pan the graph clean
   * off-screen — translateExtent is set to ±4.5 viewports so at k=0.2
   * there's ~4 viewports of slack in every direction. The bbox-overlap
   * test only triggers when *no* node is visible, so a partially
   * off-screen graph still pans freely.
   */
  const PAN_RESCUE_MARGIN = 40;
  function clampZoom(
    this: GraphCanvas<ICityGraphNodeData, ICityGraphLinkData>,
    event: ZoomEventInterface,
  ) {
    const ctrl = this as unknown as {
      area: HTMLCanvasElement | null | undefined;
      width: number;
      height: number;
      nodes: { x?: number; y?: number }[];
    };
    if (!ctrl.area || ctrl.width <= 0 || ctrl.height <= 0) return;
    // Only act on wheel-zoom events. Drag-pan also fires d3-zoom's
    // "zoom" event, and rescuing mid-drag fights the user's pointer —
    // they grab empty space, pull, and the canvas snaps back. Leave
    // pan alone; constrain only zoom-out wheel ticks.
    if (!(event.sourceEvent instanceof WheelEvent)) return;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    let count = 0;
    for (const n of ctrl.nodes) {
      if (typeof n.x === "number" && typeof n.y === "number") {
        if (n.x < minX) minX = n.x;
        if (n.x > maxX) maxX = n.x;
        if (n.y < minY) minY = n.y;
        if (n.y > maxY) maxY = n.y;
        count += 1;
      }
    }
    if (count === 0) return;
    const t = event.transform;
    const w = ctrl.width;
    const h = ctrl.height;
    const m = PAN_RESCUE_MARGIN;
    // bbox corners in screen space
    const sMinX = t.k * minX + t.x;
    const sMaxX = t.k * maxX + t.x;
    const sMinY = t.k * minY + t.y;
    const sMaxY = t.k * maxY + t.y;
    let nx = t.x;
    let ny = t.y;
    // Only act when the WHOLE bbox is past one edge — partial off-screen
    // (graph half-visible because user is exploring) is fine and we
    // mustn't fight it.
    if (sMaxX < m) nx = m - t.k * maxX;          // bbox entirely left of viewport
    else if (sMinX > w - m) nx = (w - m) - t.k * minX; // entirely right
    if (sMaxY < m) ny = m - t.k * maxY;          // entirely above
    else if (sMinY > h - m) ny = (h - m) - t.k * minY; // entirely below
    if (nx !== t.x || ny !== t.y) {
      const ZoomTransform = (t as unknown as {
        constructor: new (k: number, x: number, y: number) => typeof t;
      }).constructor;
      const clamped = new ZoomTransform(t.k, nx, ny);
      event.transform = clamped;
      (ctrl.area as unknown as { __zoom: unknown }).__zoom = clamped;
    }
  }

  /** Fit-to-content recenter. Computes the bbox of currently simulated
   * nodes and picks a (k, tx, ty) ZoomTransform that centres the bbox
   * inside the canvas with a small padding. Falls back to (1, w/2, h/2)
   * if positions aren't ready yet. The lib doesn't expose a public API
   * for this — we patch the protected `areaTransform` plus the d3-zoom
   * stash on the canvas DOM so a subsequent wheel resumes from here.
   */
  function recenter() {
    if (!graphController) return;
    type T = { x: number; y: number; k: number; constructor: new (k: number, x: number, y: number) => unknown };
    const ctrl = graphController as unknown as {
      area: HTMLCanvasElement | null | undefined;
      areaTransform: T;
      width: number;
      height: number;
      nodes: { x?: number; y?: number }[];
      tick: () => void;
    };
    if (!ctrl.area) return;
    const ZoomTransform = ctrl.areaTransform.constructor;

    const padding = 60;
    let centered: T;
    const xs: number[] = [];
    const ys: number[] = [];
    for (const n of ctrl.nodes) {
      if (typeof n.x === "number" && typeof n.y === "number") {
        xs.push(n.x);
        ys.push(n.y);
      }
    }
    if (xs.length && ctrl.width > 0 && ctrl.height > 0) {
      const minX = Math.min(...xs);
      const maxX = Math.max(...xs);
      const minY = Math.min(...ys);
      const maxY = Math.max(...ys);
      const bboxW = Math.max(1, maxX - minX);
      const bboxH = Math.max(1, maxY - minY);
      const availableW = Math.max(1, ctrl.width - 2 * padding);
      const availableH = Math.max(1, ctrl.height - 2 * padding);
      // Cap zoom so single-node graphs don't blow up to 50x.
      const k = Math.min(availableW / bboxW, availableH / bboxH, 2.0);
      const cx = (minX + maxX) / 2;
      const cy = (minY + maxY) / 2;
      centered = new ZoomTransform(
        k,
        ctrl.width / 2 - cx * k,
        ctrl.height / 2 - cy * k,
      ) as T;
    } else {
      centered = new ZoomTransform(1, ctrl.width / 2, ctrl.height / 2) as T;
    }

    ctrl.areaTransform = centered;
    (ctrl.area as unknown as { __zoom: unknown }).__zoom = centered;
    ctrl.tick();
  }

  defineExpose({ recenter, collectPositions });

  /** update settings */
  watch(
    () => [props.theme, selectedNodes.value, selectedLink.value] as const,
    ([theme, nodes, link]) => {
      if (!graphController) return;

      graphController.changeSettings({
        nodeSettings: { options: getNodeOptions(DEFAULT_SETTINGS.nodeOptions, nodes, theme) },
        linkSettings: { options: getLinkOptions(DEFAULT_SETTINGS.linkOptions, link, theme) },
      });
    },
    { immediate: true },
  );
  /** update data */
  watch(
    checkedGraph,
    (graph) => {
      if (!graphController) return;

      graphController.changeData({ links: toRaw(graph.links), nodes: toRaw(graph.nodes) }, 0.3);
    },
    { immediate: true },
  );
  /** init graph */
  watch(
    graphRef,
    (graphRef, _, clean) => {
      if (!graphRef) return;

      const controller = new GraphCanvas<ICityGraphNodeData, ICityGraphLinkData>({
        root: graphRef,
        links: toRaw(checkedGraph.value.links),
        nodes: seedPositions(toRaw(checkedGraph.value.nodes)),
        forceSettings: DEFAULT_SETTINGS.forceSettings,
        graphSettings: DEFAULT_SETTINGS.graphSettings,
        highlightSettings: DEFAULT_SETTINGS.highlightSettings,
        linkSettings: {
          ...DEFAULT_SETTINGS.linkSettings,
          options: getLinkOptions(DEFAULT_SETTINGS.linkOptions, null, props.theme),
        },
        nodeSettings: {
          ...DEFAULT_SETTINGS.nodeSettings,
          options: getNodeOptions(DEFAULT_SETTINGS.nodeOptions, [], props.theme),
        },
        listeners: {
          onClick,
          onSimulationEnd: emitPositions,
          onEndDragFinished: emitPositions,
          onZoom: clampZoom,
        },
      });

      graphController = controller;
      clean(() => {
        controller.destroy();
        graphController = undefined;
      });
    },
    { immediate: true },
  );
</script>

<template>
  <div ref="graph" :class="$style.graph"></div>
</template>

<style lang="scss" module>
  .graph {
    width: 100%;
    height: 100%;
    position: relative;
  }
</style>
