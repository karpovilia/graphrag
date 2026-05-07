import { defineNuxtConfig } from "nuxt/config";

// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: "2025-10-11",
  devtools: { enabled: false },
  alias: {
    dayjs: "dayjs",
    fuzzysort: "fuzzysort",
    lodash: "lodash",
  },
  // R2 backend is single-instance local; disable the crawler so deploys
  // don't try to hit /api/corpora during nuxt build.
  nitro: {
    prerender: {
      crawlLinks: false,
    },
    // Dev proxy: NUXT_API_PROXY_TARGET points the SPA at the FastAPI
    // process; adjusting at runtime via env (no rebuild).
    devProxy: {
      "/api": {
        target: process.env.NUXT_API_PROXY_TARGET ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },

  build: {
    transpile: ["@krainovsd/vue-ui", "@krainovsd/js-helpers", "@krainovsd/graph"],
  },
  typescript: {
    typeCheck: true,
  },
  // Phase 6.11 — single source for the API base. NUXT_PUBLIC_API_BASE
  // (env, runtime) overrides the default, which keeps it relative so
  // the dev proxy above forwards /api straight to FastAPI.
  runtimeConfig: {
    public: {
      apiBase: "",
    },
  },
  app: {
    head: {
      title: "GraphRAG Explorer",
      htmlAttrs: {
        lang: "ru",
      },
      link: [
        {
          rel: "icon",
          type: "image/x-icon",
          href: "/favicon.ico",
        },
      ],
    },
  },
});
