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
  };

  const props = defineProps<Props>();
  const graphRef = useTemplateRef("graph");
  let graphController: GraphCanvas<ICityGraphNodeData, ICityGraphLinkData> | undefined;
  const selectedNodes = defineModel<id[]>("selectedNodes", { default: [] });
  const selectedLink = defineModel<id | null>("selectedLink", { default: null });
  const checkedGraph = computed(() => getCorrectData(props.graph.nodes, props.graph.links));

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
        nodes: toRaw(checkedGraph.value.nodes),
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
