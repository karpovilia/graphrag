<script setup lang="ts">
  import { isArray } from "@krainovsd/js-helpers";
  import { VText } from "@krainovsd/vue-ui";
  import { useAsyncData } from "nuxt/app";
  import type { ICityGraphImportMap } from "@/entities/cities";
  import { createPagePath } from "@/entities/tech";

  const { data: imports } = await useAsyncData<ICityGraphImportMap[]>("import-map", () =>
    $fetch("/api/import-map"),
  );
</script>

<template>
  <div :class="$style.base">
    <VText :size="'lg'">Доступные графы:</VText>
    <div :class="$style.list">
      <template v-if="isArray(imports)">
        <div v-for="item in imports" :key="item.id" :class="$style.item">
          <NuxtLink :to="createPagePath.graph(item.id)"> {{ item.name }}</NuxtLink>
        </div>
      </template>
      <template v-if="isArray(imports)">
        <div v-for="item in imports" :key="item.id" :class="$style.item">
          <NuxtLink :to="createPagePath.graph(item.id)"> {{ item.name }}</NuxtLink>
        </div>
      </template>
    </div>
  </div>
</template>

<style lang="scss" module>
  .base {
    display: flex;
    flex-direction: column;
    gap: var(--ksd-padding);
    overflow: hidden;
    width: 100%;
    height: 100%;
  }

  .item {
    display: flex;
    align-items: center;
  }

  .list {
    display: flex;
    flex-direction: column;
    overflow: auto;
    width: 100%;
    height: 100%;
    gap: var(--ksd-padding-xs);
  }
</style>
