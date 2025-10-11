<script setup lang="ts">
  import { getByPath, isArray } from "@krainovsd/js-helpers";
  import { VHomeOutlined } from "@krainovsd/vue-icons";
  import { VButton, VText } from "@krainovsd/vue-ui";
  import { useAsyncData, useRoute } from "nuxt/app";
  import { computed, ref, useTemplateRef } from "vue";
  import { createPagePath, themeBehaviorSubject } from "@/entities/tech";
  import CityGraph from "@/components/organisms/CityGraph/CityGraph.vue";
  import type { ICityGraph } from "@/components/organisms/CityGraph/city-graph.types";
  import CityInfo, {
    type ICityLinkInfo,
    type ICityNodeInfo,
  } from "@/components/organisms/CityInfo/CityInfo.vue";

  const route = useRoute();
  const { data: info } = await useAsyncData<{ name: string; graph: ICityGraph }>(
    `graph/${route.params.id}`,
    () => $fetch(`/api/graph/${route.params.id}`),
  );
  const theme = themeBehaviorSubject.useSubscribe();
  const selectedNodes = ref<id[]>([]);
  const selectedLink = ref<id | null>(null);
  const containerRef = useTemplateRef("container");

  const selectedNodeInfo = computed<ICityNodeInfo[]>(() => {
    if (!info.value?.graph?.nodes || selectedNodes.value.length === 0) return [];

    const nodes: ICityNodeInfo[] = [];

    for (let i = 0; i < info.value.graph.nodes.length; i++) {
      const node = info.value.graph.nodes[i];
      if (selectedNodes.value.includes(node.id)) {
        nodes.push({ id: node.id, name: node.name ?? "No Name", texts: node.data?.texts ?? [] });
      }
    }

    return nodes;
  });
  // eslint-disable-next-line @typescript-eslint/no-redundant-type-constituents
  const selectedLinkInfo = computed<null | ICityLinkInfo>(() => {
    if (!info.value?.graph?.links || selectedLink.value == undefined) return null;

    for (let i = 0; i < info.value.graph.links.length; i++) {
      const link = info.value.graph.links[i];
      if (link.data?.id === selectedLink.value) {
        return {
          explanation: link.data?.explanation ?? "",
          name: `${getByPath(link, "source.name")} - ${getByPath(link, "target.name")}`,
          id: link.data.id,
        };
      }
    }

    return null;
  });
</script>

<template>
  <div ref="container" :class="$style.base">
    <div :class="$style.graph">
      <div :class="$style.header">
        <NuxtLink :to="createPagePath.home">
          <VButton>
            <template #icon>
              <VHomeOutlined />
            </template>
          </VButton>
        </NuxtLink>
        <VText size="lg"> {{ info?.name }}</VText>
      </div>
      <CityGraph
        v-if="info != undefined && isArray(info.graph.links) && isArray(info.graph.nodes)"
        v-model:selected-link="selectedLink"
        v-model:selected-nodes="selectedNodes"
        :theme="theme"
        :graph="info.graph"
      />
    </div>
    <CityInfo
      v-if="info != undefined"
      :mount-root="containerRef"
      :selected-nodes="selectedNodeInfo"
      :selected-link="selectedLinkInfo"
      @close="
        () => {
          selectedLink = null;
          selectedNodes = [];
        }
      "
    />
  </div>
</template>

<style lang="scss" module>
  .base {
    display: flex;
    gap: var(--ksd-padding);
    width: 100%;
    height: 100%;
    overflow: hidden;
  }
  .graph {
    display: flex;
    flex-direction: column;
    gap: var(--ksd-padding);
    width: 100%;
    height: 100%;
    flex: 1;
  }

  .header {
    display: flex;
    align-items: center;
    gap: var(--ksd-padding-lg);
  }
</style>
