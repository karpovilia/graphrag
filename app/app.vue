<script setup lang="ts">
  import { VThemeProvider, extractThemeVariables } from "@krainovsd/vue-ui";
  import "@krainovsd/vue-ui/styles";
  import { useHead } from "nuxt/app";
  import RootProvider from "./components/providers/RootProvider.vue";
  import { THEME_CONFIG, themeBehaviorSubject } from "./entities/tech";
  import "./global.scss";

  const theme = themeBehaviorSubject.useSubscribe();

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
