// Auth state shared across the app via useState (Nuxt singleton).
// `user` is null until /api/auth/me has been resolved at least once;
// it stays null when the call returns 401 (anonymous visitor).

import { useNuxtApp, useState } from "nuxt/app";
import { computed } from "vue";

import { useApi } from "@/lib/api-client";

export type CurrentUser = {
  id: string;
  email: string;
  language: "ru" | "en";
  created_at: string;
};

export function useAuth() {
  const api = useApi();
  const user = useState<CurrentUser | null>("auth:user", () => null);
  const loaded = useState<boolean>("auth:loaded", () => false);
  const loading = useState<boolean>("auth:loading", () => false);

  async function refresh(): Promise<CurrentUser | null> {
    loading.value = true;
    try {
      const me = await api.auth.me();
      user.value = me;
      await syncLocale(me.language);
      return me;
    } catch {
      user.value = null;
      return null;
    } finally {
      loaded.value = true;
      loading.value = false;
    }
  }

  async function login(email: string, password: string): Promise<CurrentUser> {
    const me = await api.auth.login({ email, password });
    user.value = me;
    loaded.value = true;
    await syncLocale(me.language);
    return me;
  }

  async function register(
    email: string,
    password: string,
    language: "ru" | "en",
  ): Promise<CurrentUser> {
    const me = await api.auth.register({ email, password, language });
    user.value = me;
    loaded.value = true;
    await syncLocale(me.language);
    return me;
  }

  async function logout(): Promise<void> {
    await api.auth.logout();
    user.value = null;
  }

  async function setLanguage(language: "ru" | "en"): Promise<void> {
    if (!user.value) return;
    const me = await api.auth.patchMe({ language });
    user.value = me;
    await syncLocale(language);
  }

  // Push the user's saved preference into vue-i18n. Anonymous visitors
  // get whatever the browser-detect resolved to; logged-in users
  // override that with their stored choice.
  async function syncLocale(language: "ru" | "en"): Promise<void> {
    const nuxt = useNuxtApp();
    const i18n = nuxt.$i18n as
      | { setLocale?: (l: string) => Promise<void> | void }
      | undefined;
    if (i18n?.setLocale) {
      await i18n.setLocale(language);
    }
  }

  return {
    user,
    loaded,
    loading,
    isAuthenticated: computed(() => user.value !== null),
    refresh,
    login,
    register,
    logout,
    setLanguage,
  };
}
