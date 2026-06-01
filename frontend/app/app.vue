<script setup lang="ts">
  import { VThemeProvider, extractThemeVariables } from "@krainovsd/vue-ui";
  import "@krainovsd/vue-ui/styles";
  import { useHead } from "nuxt/app";
  import { useRoute } from "vue-router";
  import { computed } from "vue";

  import AppHeader from "./components/organisms/AppHeader/AppHeader.vue";
  import RootProvider from "./components/providers/RootProvider.vue";
  import { THEME_CONFIG, themeBehaviorSubject } from "./entities/tech";
  import "./global.scss";

  const theme = themeBehaviorSubject.useSubscribe();
  const route = useRoute();
  // Login/register render their own full-page card; the global header
  // would only get in the way.
  const showHeader = computed(
    () => !["/login", "/register"].includes(route.path),
  );

  if (import.meta.server) {
    useHead({
      style: [
        {
          innerHTML: `:root { ${extractThemeVariables(theme.value, THEME_CONFIG)} } html{ font-size: 14px; }`,
        },
      ],
    });
  }
</script>

<template>
  <div :class="$style.base">
    <VThemeProvider :theme-config="THEME_CONFIG" :theme="theme" :font-size="14">
      <RootProvider>
        <AppHeader v-if="showHeader" />
        <NuxtPage />
      </RootProvider>
    </VThemeProvider>
  </div>
</template>

<style lang="scss" module>
  .base {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    overflow: hidden;
  }
</style>
