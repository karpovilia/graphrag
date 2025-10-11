<script setup lang="ts">
  import { isArray } from "@krainovsd/js-helpers";
  import { VText } from "@krainovsd/vue-ui";
  import { useAsyncData, useRoute } from "nuxt/app";
  import { themeBehaviorSubject } from "@/entities/tech";
  import CityGraph from "@/components/organisms/CityGraph/CityGraph.vue";
  import type { ICityGraph } from "@/components/organisms/CityGraph/city-graph.types";

  const route = useRoute();
  const { data: info } = await useAsyncData<{ name: string; graph: ICityGraph }>(
    `graph/${route.params.id}`,
    () => $fetch(`/api/graph/${route.params.id}`),
  );
  const theme = themeBehaviorSubject.useSubscribe();
</script>

<template>
  <div :class="$style.base">
    <VText size="lg"> {{ info?.name }}</VText>
    <CityGraph
      v-if="info != undefined && isArray(info.graph.links) && isArray(info.graph.nodes)"
      :theme="theme"
      :graph="info.graph"
    />
  </div>
</template>

<style lang="scss" module>
  .base {
    display: flex;
    flex-direction: column;
    gap: var(--ksd-padding);
    width: 100%;
    height: 100%;
    overflow: hidden;
  }
</style>
