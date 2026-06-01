import { defineNuxtRouteMiddleware, navigateTo } from "nuxt/app";

import { useAuth } from "@/composables/use-auth";

// Pages that opt into auth via `definePageMeta({ middleware: "auth" })`
// redirect anonymous visitors to /login (with ?next=… so we can return
// after a successful sign-in).

export default defineNuxtRouteMiddleware(async (to) => {
  const auth = useAuth();
  if (!auth.loaded.value) {
    await auth.refresh();
  }
  if (auth.user.value === null) {
    const next = to.fullPath && to.fullPath !== "/login" ? to.fullPath : "/";
    return navigateTo(`/login?next=${encodeURIComponent(next)}`);
  }
});
