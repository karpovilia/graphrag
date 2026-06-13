<script setup lang="ts">
import { onBeforeUnmount, onMounted, toRaw, ref, watch } from "vue";
import {
  GraphCanvas,
  FORCE_SETTINGS,
  GRAPH_SETTINGS,
  HIGHLIGHT_SETTINGS,
  LINK_OPTIONS,
  LINK_SETTINGS,
  NODE_OPTIONS,
  NODE_SETTINGS,
} from "@krainovsd/graph";
import type { RenderGraph } from "@/lib/api";

const props = defineProps<{
  graph: RenderGraph | null;
  focusIds: string[];
  deltaStatus: Record<string, string>;
}>();
const emit = defineEmits<{ (e: "select-node", id: string | null): void }>();

const root = ref<HTMLElement | null>(null);
// The engine's generics are heavy; treat the controller loosely in the view.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let controller: any = null;

const DELTA_BORDER: Record<string, string> = {
  born: "#34a853",
  dead: "#ea4335",
  changed: "#fbbc05",
};

function cloneData() {
  const g = props.graph;
  if (!g) return { nodes: [], links: [] };
  return {
    nodes: g.graph.nodes.map((n) => ({ ...n, data: { ...n.data } })),
    links: g.graph.links.map((l) => ({ ...l, data: { ...l.data } })),
  };
}

function nodeOptions() {
  const focus = new Set(props.focusIds);
  const focusing = focus.size > 0;
  const delta = props.deltaStatus;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (node: any) => {
    const inFocus = focus.has(node.id);
    const dim = focusing && !inFocus;
    const deltaBorder = node.id in delta ? DELTA_BORDER[delta[node.id]] : undefined;
    const pinned = node.data?.pinned;
    const accent = deltaBorder ?? (pinned ? "#f9ab00" : inFocus ? "#1a73e8" : undefined);
    return {
      ...NODE_OPTIONS,
      label: node.name,
      color: node.data?.color ?? NODE_OPTIONS.color,
      radius: 6 + (node.data?.size ?? 1) * 2,
      alpha: dim ? 0.12 : NODE_OPTIONS.alpha ?? 1,
      labelSize: 5,
      labelAlpha: dim ? 0.1 : 1,
      labelColor: dim ? "#b0b4bb" : "#3c4043",
      borderColor: accent ?? NODE_OPTIONS.borderColor,
      borderWidth: accent ? 1.4 : NODE_OPTIONS.borderWidth,
    };
  };
}

function linkOptions() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (link: any) => ({
    ...LINK_OPTIONS,
    width: 0.5,
    color: link.data?.color ?? LINK_OPTIONS.color ?? "#5b6470",
    arrowColor: link.data?.color ?? LINK_OPTIONS.arrowColor ?? "#5b6470",
  });
}

function applyOptions() {
  if (!controller) return;
  try {
    controller.changeSettings.call(toRaw(controller), {
      nodeSettings: { ...NODE_SETTINGS, options: nodeOptions() },
      linkSettings: { ...LINK_SETTINGS, options: linkOptions() },
      forceSettings: {
        ...FORCE_SETTINGS,
        linkDistance: 90,
        chargeForce: true,
        chargeStrength: -320,
        collideForce: true,
        collideAdditionalRadius: 8,
      },
      highlightSettings: HIGHLIGHT_SETTINGS,
      graphSettings: { ...GRAPH_SETTINGS, zoomExtent: [0.05, 12], zoomInitial: 2.2 },
    });
  } catch {
    /* engine not ready */
  }
}

onMounted(() => {
  if (!root.value) return;
  const data = cloneData();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const GC = GraphCanvas as any;
  controller = new GC({
    root: root.value,
    nodes: data.nodes,
    links: data.links,
    graphSettings: { ...GRAPH_SETTINGS, zoomExtent: [0.05, 12], zoomInitial: 2.2 },
    listeners: {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      onClick: (_e: unknown, node: any) => emit("select-node", node?.id ?? null),
    },
  });
  applyOptions();
});

onBeforeUnmount(() => {
  try {
    controller?.destroy?.call?.(toRaw(controller));
  } catch {
    /* noop */
  }
  controller = null;
});

watch(
  () => props.graph,
  () => {
    if (!controller) return;
    try {
      controller.changeData.call(toRaw(controller), cloneData(), 0.4);
    } catch {
      /* noop */
    }
    applyOptions();
  },
);

watch(() => [props.focusIds, props.deltaStatus], applyOptions, { deep: true });
</script>

<template>
  <div ref="root" class="graph-canvas" />
</template>

<style scoped>
.graph-canvas {
  width: 100%;
  height: 100%;
  background: var(--gc-canvas-bg, #0f1115);
}
</style>
