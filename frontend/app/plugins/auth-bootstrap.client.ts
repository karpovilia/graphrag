// On client startup, hit /api/auth/me once so the rest of the app
// can synchronously read `useAuth().user`. .client.ts so it doesn't
// run during nuxi prerender (we ship as SPA anyway, but the marker
// is safer).

import { defineNuxtPlugin } from "nuxt/app";

import { useAuth } from "@/composables/use-auth";

export default defineNuxtPlugin(async () => {
  const auth = useAuth();
  await auth.refresh();
});
