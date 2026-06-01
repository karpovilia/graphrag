<script setup lang="ts">
  import { navigateTo } from "nuxt/app";
  import { useRouter } from "vue-router";
  import { onMounted, ref } from "vue";
  import { useI18n } from "vue-i18n";

  import { useAuth } from "@/composables/use-auth";

  const { t } = useI18n();
  const auth = useAuth();
  const router = useRouter();

  // Inline auth-guard: middleware/auth.ts exists for pages that opt in via
  // definePageMeta, but the project's tsconfig doesn't include the macro
  // type. Using a plain onMounted guard keeps the same UX without fighting
  // the toolchain.
  onMounted(async () => {
    if (!auth.loaded.value) await auth.refresh();
    if (auth.user.value === null) {
      await navigateTo("/login?next=/profile");
    }
  });

  const saving = ref(false);
  const error = ref<string | null>(null);

  async function onLanguageChange(e: Event) {
    const target = e.target as HTMLSelectElement;
    const lang = target.value === "en" ? "en" : "ru";
    saving.value = true;
    error.value = null;
    try {
      await auth.setLanguage(lang);
    } catch (e2) {
      error.value = e2 instanceof Error ? e2.message : String(e2);
    } finally {
      saving.value = false;
    }
  }

  async function onLogout() {
    await auth.logout();
    await router.push("/login");
  }
</script>

<template>
  <div :class="$style.page" v-if="auth.user.value">
    <header :class="$style.header">
      <NuxtLink to="/" :class="$style.back">{{ t("common.back") }}</NuxtLink>
      <h1 :class="$style.title">{{ t("profile.title") }}</h1>
    </header>

    <section :class="$style.section">
      <h2 :class="$style.subhead">{{ t("profile.accountSection") }}</h2>
      <dl :class="$style.metrics">
        <div>
          <dt>{{ t("common.email") }}</dt>
          <dd>{{ auth.user.value.email }}</dd>
        </div>
        <div>
          <dt>{{ t("profile.createdAt") }}</dt>
          <dd>{{ new Date(auth.user.value.created_at).toLocaleString() }}</dd>
        </div>
      </dl>
    </section>

    <section :class="$style.section">
      <h2 :class="$style.subhead">{{ t("profile.languageSection") }}</h2>
      <p :class="$style.note">{{ t("profile.languageDescription") }}</p>
      <select
        :class="$style.select"
        :value="auth.user.value.language"
        :disabled="saving"
        @change="onLanguageChange"
      >
        <option value="ru">{{ t("profile.languageRu") }}</option>
        <option value="en">{{ t("profile.languageEn") }}</option>
      </select>
      <p v-if="saving" :class="$style.note">{{ t("common.loading") }}</p>
      <p v-if="error" :class="$style.error">{{ error }}</p>
    </section>

    <button type="button" :class="$style.logoutBtn" @click="onLogout">
      {{ t("auth.logoutCta") }}
    </button>
  </div>
</template>

<style lang="scss" module>
  .page {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-lg);
    padding: var(--gr-space-xl);
    max-width: 720px;
    margin: 0 auto;
  }
  .header {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
  }
  .back {
    color: var(--ksd-text-secondary-color);
    text-decoration: none;
    font-size: 0.875rem;
    width: fit-content;

    &:hover {
      color: var(--ksd-accent-color);
    }
  }
  .title {
    margin: 0;
    font-size: 1.75rem;
    font-weight: 700;
  }
  .section {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-sm);
  }
  .subhead {
    margin: 0;
    font-size: 1.1rem;
    font-weight: 600;
  }
  .note {
    margin: 0;
    font-size: 0.875rem;
    color: var(--ksd-text-secondary-color);
  }
  .metrics {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gr-space-lg);
    margin: 0;
    padding: var(--gr-space-md);
    background: var(--ksd-card-bg-color);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-md);

    dt {
      font-size: 0.7rem;
      color: var(--ksd-text-secondary-color);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    dd {
      margin: 0;
      font-size: 1rem;
      color: var(--ksd-text-main-color);
    }
  }
  .select {
    width: fit-content;
    min-width: 200px;
    padding: var(--gr-space-xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
  }
  .error {
    margin: 0;
    color: var(--gr-status-failed);
    font-size: 0.875rem;
  }
  .logoutBtn {
    align-self: flex-start;
    padding: var(--gr-space-xs) var(--gr-space-md);
    background: transparent;
    color: var(--gr-status-failed);
    border: 1px solid var(--gr-status-failed);
    border-radius: var(--gr-radius-sm);
    cursor: pointer;
    font-size: 0.875rem;

    &:hover {
      background: var(--gr-status-failed);
      color: white;
    }
  }
</style>
