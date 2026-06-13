<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, toRaw, watch } from "vue";
import { GraphCanvas } from "@krainovsd/graph";
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
    const status = delta[node.id];
    const deltaBorder = status ? DELTA_BORDER[status] : undefined;
    const pinned = node.data?.pinned;
    return {
      label: node.name,
      color: node.data?.color ?? "#4f86f7",
      radius: node.data?.size ?? 1.2,
      alpha: dim ? 0.12 : 1,
      textAlpha: dim ? 0.12 : 1,
      labelAlpha: dim ? 0.12 : 1,
      borderColor: deltaBorder ?? (pinned ? "#f9ab00" : inFocus ? "#1a73e8" : node.data?.borderColor),
      borderWidth: deltaBorder ? 1.4 : pinned || inFocus ? 0.9 : node.data?.borderColor ? 0.5 : 0,
    };
  };
}

function linkOptions() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (link: any) => ({
    color: link.data?.color ?? "#9aa0a6",
    width: 0.12,
  });
}

function applyOptions() {
  if (!controller) return;
  try {
    controller.changeSettings.call(toRaw(controller), {
      nodeSettings: { options: nodeOptions() },
      linkSettings: { options: linkOptions() },
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
    graphSettings: { zoomExtent: [0.1, 10], translateExtentCoefficient: [10, 10] },
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
    const data = cloneData();
    try {
      controller.changeData.call(toRaw(controller), data, 0.3);
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
