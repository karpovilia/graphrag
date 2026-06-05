<script setup lang="ts">
  import { useAsyncData } from "nuxt/app";
  import { computed } from "vue";
  import { useRoute } from "vue-router";

  import NodeDrawer from "@/components/organisms/NodeDrawer/NodeDrawer.vue";
  import ErrorBanner from "@/components/molecules/ErrorBanner/ErrorBanner.vue";
  import { useApi } from "@/lib/api-client";
  import type { GraphVariant } from "@/entities/api";

  const route = useRoute();
  const variantId = String(route.params.variantId);
  const nodeId = String(route.params.nodeId);
  const api = useApi();

  const { data: variant, error: variantError } = await useAsyncData(
    `node-page:variant:${variantId}`,
    () => api.graphs.get(variantId),
  );
  const { data: nodes, refresh: refreshNodes } = await useAsyncData(
    `node-page:nodes:${variantId}`,
    () => api.graphs.listNodes(variantId),
    { default: () => [] },
  );
  const { data: edges, refresh: refreshEdges } = await useAsyncData(
    `node-page:edges:${variantId}`,
    () => api.graphs.listEdges(variantId),
    { default: () => [] },
  );

  const node = computed(
    () => (nodes.value ?? []).find((n) => String(n.id) === nodeId) ?? null,
  );

  function onVariantChanged(v: GraphVariant) {
    if (variant.value) variant.value = v;
    refreshNodes();
    refreshEdges();
  }
  function closeWindow() {
    window.close();
  }
</script>

<template>
  <div :class="$style.page">
    <ErrorBanner v-if="variantError" :error="variantError" />
    <NodeDrawer
      v-else-if="variant && node"
      :node="node"
      :variant="variant"
      :all-nodes="nodes ?? []"
      :all-edges="edges ?? []"
      standalone
      @variant-changed="onVariantChanged"
      @close="closeWindow"
    />
    <p v-else :class="$style.loading">…</p>
  </div>
</template>

<style module>
  .page {
    height: 100vh;
    background: var(--ksd-bg-color);
  }
  .loading {
    padding: 2rem;
    color: var(--ksd-text-secondary-color);
  }
</style>
