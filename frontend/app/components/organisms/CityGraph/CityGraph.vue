<script setup lang="ts">
  import { GraphCanvas } from "@krainovsd/graph";
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
