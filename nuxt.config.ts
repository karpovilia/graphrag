import { defineNuxtConfig } from "nuxt/config";

// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: "2025-10-11",
  devtools: { enabled: true },
  alias: {
    dayjs: "dayjs",
    fuzzysort: "fuzzysort",
    lodash: "lodash",
  },
  build: {
    transpile: ["@krainovsd/vue-ui", "@krainovsd/js-helpers", "@krainovsd/graph"],
  },
  vite: {},
  typescript: {
    typeCheck: true,
  },
  app: {
    head: {
      title: "Graph",
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
