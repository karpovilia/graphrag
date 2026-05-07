<script setup lang="ts">
  import { navigateTo } from "nuxt/app";

  // Phase 6 — root used to be a static "available datasets" stub. The
  // R2 entry point is the corpus list; redirect on setup so existing
  // bookmarks keep working.
  await navigateTo("/corpora", { replace: true });
</script>

<template>
  <div></div>
</template>
