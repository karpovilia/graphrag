<script setup lang="ts">
  import { useRoute, useRouter } from "vue-router";
  import { ref } from "vue";
  import { useI18n } from "vue-i18n";

  import { useAuth } from "@/composables/use-auth";

  const { t } = useI18n();
  const auth = useAuth();
  const route = useRoute();
  const router = useRouter();

  const email = ref("");
  const password = ref("");
  const submitting = ref(false);
  const error = ref<string | null>(null);

  async function onSubmit() {
    error.value = null;
    submitting.value = true;
    try {
      await auth.login(email.value, password.value);
      const next = typeof route.query.next === "string" ? route.query.next : "/";
      await router.push(next);
    } catch (e) {
      error.value = e instanceof Error ? e.message : t("auth.errorInvalid");
    } finally {
      submitting.value = false;
    }
  }
</script>

<template>
  <div :class="$style.shell">
    <form :class="$style.card" @submit.prevent="onSubmit">
      <h1 :class="$style.title">{{ t("auth.loginTitle") }}</h1>

      <label :class="$style.field">
        <span>{{ t("common.email") }}</span>
        <input
          v-model="email"
          type="email"
          required
          autocomplete="email"
          autofocus
        />
      </label>

      <label :class="$style.field">
        <span>{{ t("common.password") }}</span>
        <input
          v-model="password"
          type="password"
          required
          minlength="1"
          autocomplete="current-password"
        />
      </label>

      <p v-if="error" :class="$style.error">{{ error }}</p>

      <button type="submit" :class="$style.cta" :disabled="submitting">
        {{ submitting ? t("common.loading") : t("auth.loginCta") }}
      </button>

      <p :class="$style.alt">
        {{ t("auth.noAccount") }}
        <NuxtLink to="/register">{{ t("nav.register") }}</NuxtLink>
      </p>
    </form>
  </div>
</template>

<style lang="scss" module>
  .shell {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: var(--gr-space-lg);
    background: var(--ksd-bg-color);
  }
  .card {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-md);
    width: 100%;
    max-width: 360px;
    padding: var(--gr-space-xl);
    background: var(--ksd-card-bg-color);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-md);
  }
  .title {
    margin: 0;
    font-size: 1.5rem;
    font-weight: 600;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
    font-size: 0.875rem;

    input {
      padding: var(--gr-space-xs) var(--gr-space-sm);
      border: 1px solid var(--ksd-border-color);
      border-radius: var(--gr-radius-sm);
      background: var(--ksd-bg-color);
      color: var(--ksd-text-main-color);
      font-size: 1rem;
    }
  }
  .error {
    margin: 0;
    color: var(--gr-status-failed);
    font-size: 0.875rem;
  }
  .cta {
    padding: var(--gr-space-sm);
    background: var(--ksd-accent-color);
    color: white;
    border: none;
    border-radius: var(--gr-radius-sm);
    font-weight: 600;
    cursor: pointer;

    &:disabled {
      opacity: 0.6;
      cursor: wait;
    }
  }
  .alt {
    margin: 0;
    font-size: 0.875rem;
    color: var(--ksd-text-secondary-color);
    text-align: center;

    a {
      color: var(--ksd-accent-color);
      text-decoration: none;
    }
  }
</style>
