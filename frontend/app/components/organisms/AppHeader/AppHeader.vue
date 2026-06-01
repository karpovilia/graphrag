<script setup lang="ts">
  import { useRoute, useRouter } from "vue-router";
  import { computed } from "vue";
  import { useI18n } from "vue-i18n";

  import { useAuth } from "@/composables/use-auth";

  const { t, locale } = useI18n();
  const auth = useAuth();
  const route = useRoute();
  const router = useRouter();

  const onCorpora = computed(() => route.path.startsWith("/corpora"));

  async function onLogout() {
    await auth.logout();
    await router.push("/login");
  }

  // Anonymous visitors get a session-only locale switch via the vue-i18n
  // composer's `locale` ref. Logged-in users go through useAuth.setLanguage
  // which round-trips the choice to the server (PATCH /api/auth/me).
  async function onLocaleChange(e: Event) {
    const target = e.target as HTMLSelectElement;
    const next = target.value === "en" ? "en" : "ru";
    if (auth.user.value) {
      await auth.setLanguage(next);
    } else {
      locale.value = next;
    }
  }
</script>

<template>
  <header :class="$style.bar" aria-label="App header">
    <NuxtLink to="/corpora" :class="[$style.link, onCorpora ? $style.linkActive : '']">
      {{ t("nav.corpora") }}
    </NuxtLink>

    <span :class="$style.spacer" />

    <select
      :class="$style.localeSelect"
      :value="locale"
      :title="t('common.language')"
      @change="onLocaleChange"
    >
      <option value="ru">RU</option>
      <option value="en">EN</option>
    </select>

    <template v-if="auth.user.value">
      <NuxtLink to="/profile" :class="$style.user" :title="auth.user.value.email">
        {{ auth.user.value.email }}
      </NuxtLink>
      <button type="button" :class="$style.iconBtn" @click="onLogout">
        {{ t("nav.logout") }}
      </button>
    </template>
    <template v-else>
      <NuxtLink to="/login" :class="$style.link">{{ t("nav.login") }}</NuxtLink>
      <NuxtLink to="/register" :class="$style.linkPrimary">
        {{ t("nav.register") }}
      </NuxtLink>
    </template>
  </header>
</template>

<style lang="scss" module>
  .bar {
    display: flex;
    align-items: center;
    gap: var(--gr-space-sm);
    padding: var(--gr-space-xs) var(--gr-space-md);
    background: var(--ksd-card-bg-color);
    border-bottom: 1px solid var(--ksd-border-color);
    flex-shrink: 0;
  }
  .spacer {
    flex: 1;
  }
  .link {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    color: var(--ksd-text-secondary-color);
    text-decoration: none;
    border-radius: var(--gr-radius-sm);

    &:hover {
      color: var(--ksd-accent-color);
    }
  }
  .linkActive {
    color: var(--ksd-text-main-color);
    background: var(--ksd-bg-color);
  }
  .linkPrimary {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    background: var(--ksd-accent-color);
    color: white;
    text-decoration: none;
    border-radius: var(--gr-radius-sm);
  }
  .user {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    color: var(--ksd-text-main-color);
    text-decoration: none;
    font-size: 0.875rem;
    border-radius: var(--gr-radius-sm);
    max-width: 220px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;

    &:hover {
      background: var(--ksd-bg-color);
    }
  }
  .iconBtn {
    background: transparent;
    color: var(--ksd-text-secondary-color);
    border: 1px solid var(--ksd-border-color);
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border-radius: var(--gr-radius-sm);
    font-size: 0.875rem;
    cursor: pointer;

    &:hover {
      color: var(--ksd-text-main-color);
      border-color: var(--ksd-text-main-color);
    }
  }
  .localeSelect {
    padding: 2px var(--gr-space-xs);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    font-size: 0.875rem;
    cursor: pointer;
  }
</style>
