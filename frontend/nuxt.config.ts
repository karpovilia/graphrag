import { defineNuxtConfig } from "nuxt/config";

// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: "2025-10-11",
  // Local single-instance dev tool — no SEO, no public surface. SSR
  // here only buys hydration-mismatch bugs (style modules drop classes
  // on rehydrate when async data changes between server and client).
  ssr: false,
  devtools: { enabled: false },
  modules: ["@nuxtjs/i18n"],
  // @ts-expect-error — @nuxtjs/i18n module config is augmented in .nuxt/
  // types but the project's tsconfig (extends @krainovsd/presets) does
  // not include them, so vue-tsc doesn't see this key. Runtime is fine.
  i18n: {
    strategy: "no_prefix",
    defaultLocale: "ru",
    locales: [
      { code: "ru", name: "Русский", file: "ru.json" },
      { code: "en", name: "English", file: "en.json" },
    ],
    langDir: "locales",
    detectBrowserLanguage: {
      useCookie: true,
      cookieKey: "i18n_locale",
      alwaysRedirect: false,
      fallbackLocale: "ru",
    },
  },
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
  },
  // /api/** is proxied to FastAPI via routeRules so it works the same in
  // `nuxt dev` and `nuxt build/preview`. nitro.devProxy alone was a no-op
  // here: an empty `server/api/` directory makes nitro register /api/* as
  // its own namespace and respond 404 before devProxy fires. NUXT_API_PROXY_TARGET
  // overrides at runtime (no rebuild).
  routeRules: {
    "/api/**": {
      proxy: `${process.env.NUXT_API_PROXY_TARGET ?? "http://localhost:8000"}/api/**`,
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
  // the routeRules proxy above forwards /api straight to FastAPI.
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
