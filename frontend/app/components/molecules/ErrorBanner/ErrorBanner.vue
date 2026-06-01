<script setup lang="ts">
  // §2.5 structured error / empty-state banner. Maps HttpError.status to
  // human copy + a recovery-action slot, replacing bare error.message in
  // ResultsStep / NodeDrawer / SuggestionsSidebar / graph page (closes the
  // R2 silent-failure complaint).
  //
  //   409 → graph changed, refresh and retry
  //   404 → variant / edge not found
  //   422 → bad time window
  //   400 → t_a after t_b
  // Anything else falls back to the raw detail.

  import { computed } from "vue";
  import { useI18n } from "vue-i18n";

  import type { ApiError } from "@/lib/api-client";

  const { t } = useI18n();

  type Props = {
    error: unknown;
  };
  const props = defineProps<Props>();

  function asApiError(e: unknown): ApiError | null {
    if (e && typeof e === "object" && "status" in e) {
      return e as ApiError;
    }
    return null;
  }

  // Stable status string for e2e assertions — actual HTTP code or
  // 'generic' when the thrown error carries none.
  const statusAttr = computed(() => {
    const err = asApiError(props.error);
    return err?.status != null ? String(err.status) : "generic";
  });

  const copy = computed(() => {
    const err = asApiError(props.error);
    const status = err?.status;
    switch (status) {
      case 409:
        return { title: t("errorBanner.409Title"), body: t("errorBanner.409Body") };
      case 404:
        return { title: t("errorBanner.404Title"), body: t("errorBanner.404Body") };
      case 422:
        return { title: t("errorBanner.422Title"), body: t("errorBanner.422Body") };
      case 400:
        return { title: t("errorBanner.400Title"), body: t("errorBanner.400Body") };
      default: {
        const message =
          err?.message ??
          (props.error instanceof Error ? props.error.message : String(props.error));
        return { title: t("errorBanner.genericTitle"), body: message };
      }
    }
  });
</script>

<template>
  <div
    :class="$style.banner"
    role="alert"
    data-testid="error-banner"
    :data-status="statusAttr"
  >
    <div :class="$style.text">
      <strong :class="$style.title">{{ copy.title }}</strong>
      <span :class="$style.body">{{ copy.body }}</span>
    </div>
    <div :class="$style.action">
      <slot name="action" />
    </div>
  </div>
</template>

<style lang="scss" module>
  .banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--gr-space-md);
    padding: var(--gr-space-sm) var(--gr-space-md);
    border: 1px solid var(--gr-status-failed);
    background: rgba(239, 68, 68, 0.08);
    border-radius: var(--gr-radius-sm);
  }

  .text {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .title {
    color: var(--gr-status-failed);
    font-size: 0.9rem;
  }

  .body {
    font-size: 0.8rem;
    color: var(--ksd-text-secondary-color);
  }

  .action {
    flex-shrink: 0;
  }
</style>
