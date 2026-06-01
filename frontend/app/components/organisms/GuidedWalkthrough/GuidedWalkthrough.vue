<script setup lang="ts">
  // §2.6 spotlight overlay. Mounted at PAGE level (never inside the
  // AskWizard frame) so it can't focus-trap the wizard back-nav / chat.
  // The backdrop has pointer-events:none EXCEPT the step card, so normal
  // graph interaction continues underneath; closing restores everything.
  //
  // The spotlight cutout is positioned over the current step's target
  // (resolved by step.targetTestId → document.querySelector +
  // getBoundingClientRect). If the target is missing, we fall back to a
  // centered card with no cutout.

  import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
  import { useI18n } from "vue-i18n";

  import { useWalkthrough, type Walkthrough } from "@/composables/use-walkthrough";

  const { t } = useI18n();

  type Props = {
    /** Pass a shared instance from the page; falls back to a fresh one. */
    walkthrough?: Walkthrough;
  };
  const props = defineProps<Props>();

  const wt = props.walkthrough ?? useWalkthrough();

  type Rect = { top: number; left: number; width: number; height: number };
  const targetRect = ref<Rect | null>(null);

  function measure() {
    const id = wt.current.value?.targetTestId;
    if (!id || typeof document === "undefined") {
      targetRect.value = null;
      return;
    }
    const el = document.querySelector(`[data-testid="${id}"]`);
    if (!el) {
      targetRect.value = null;
      return;
    }
    const r = el.getBoundingClientRect();
    targetRect.value = {
      top: r.top,
      left: r.left,
      width: r.width,
      height: r.height,
    };
  }

  watch(() => [wt.active.value, wt.index.value], () => {
    if (wt.active.value) {
      // Defer one frame so a freshly-mounted target is laid out.
      requestAnimationFrame(measure);
    }
  });

  function onResize() {
    if (wt.active.value) measure();
  }

  function onKeydown(e: KeyboardEvent) {
    if (!wt.active.value) return;
    if (e.key === "Escape") {
      e.preventDefault();
      wt.dismiss();
    }
  }

  onMounted(() => {
    window.addEventListener("resize", onResize, { passive: true });
    window.addEventListener("scroll", onResize, { passive: true, capture: true });
    window.addEventListener("keydown", onKeydown);
    if (wt.active.value) requestAnimationFrame(measure);
  });

  onBeforeUnmount(() => {
    window.removeEventListener("resize", onResize);
    window.removeEventListener("scroll", onResize, { capture: true } as never);
    window.removeEventListener("keydown", onKeydown);
  });

  // Spotlight: a box-shadow ring around the target dims everything else
  // while keeping the target visually highlighted. Position the card
  // just below (or above when near the bottom) the target.
  const spotlightStyle = computed(() => {
    const r = targetRect.value;
    if (!r) return null;
    const pad = 8;
    return {
      top: `${r.top - pad}px`,
      left: `${r.left - pad}px`,
      width: `${r.width + pad * 2}px`,
      height: `${r.height + pad * 2}px`,
    };
  });

  const cardStyle = computed(() => {
    const r = targetRect.value;
    if (!r || typeof window === "undefined") {
      return { top: "50%", left: "50%", transform: "translate(-50%, -50%)" };
    }
    const below = r.top + r.height + 16;
    const tooLow = below > window.innerHeight - 200;
    const top = tooLow ? Math.max(r.top - 220, 16) : below;
    const left = Math.min(
      Math.max(r.left, 16),
      Math.max(window.innerWidth - 360, 16),
    );
    return { top: `${top}px`, left: `${left}px`, transform: "none" };
  });

  const isLast = computed(() => wt.index.value >= wt.total - 1);
</script>

<template>
  <Teleport to="body">
    <div
      v-if="wt.active.value"
      data-testid="walkthrough"
      role="dialog"
      aria-modal="true"
      :class="$style.overlay"
    >
      <!-- Dimmed backdrop. pointer-events:none so the graph stays live. -->
      <div :class="$style.backdrop" />
      <!-- Spotlight ring around the resolved target. -->
      <div
        v-if="spotlightStyle"
        :class="$style.spotlight"
        :style="spotlightStyle"
      />

      <!-- Step card — the ONLY interactive element of the overlay. -->
      <div
        data-testid="walkthrough-step"
        :data-step-index="wt.index.value"
        :class="$style.card"
        :style="cardStyle"
      >
        <div :class="$style.badge">
          {{ t("walkthrough.progress", { i: wt.index.value + 1, n: wt.total }) }}
        </div>
        <h3 :class="$style.title">{{ t(wt.current.value.titleKey) }}</h3>
        <p :class="$style.body">{{ t(wt.current.value.bodyKey) }}</p>
        <div :class="$style.controls">
          <button
            type="button"
            data-testid="walkthrough-back"
            :class="$style.btn"
            :disabled="wt.index.value === 0"
            @click="wt.back()"
          >
            {{ t("walkthrough.back") }}
          </button>
          <button
            type="button"
            data-testid="walkthrough-skip"
            :class="$style.btnGhost"
            @click="wt.skip()"
          >
            {{ t("walkthrough.skip") }}
          </button>
          <button
            type="button"
            data-testid="walkthrough-next"
            :class="$style.btnPrimary"
            @click="isLast ? wt.finish() : wt.next()"
          >
            {{ isLast ? t("walkthrough.done") : t("walkthrough.next") }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style lang="scss" module>
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 1000;
    pointer-events: none;
  }

  .backdrop {
    position: absolute;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    pointer-events: none;
  }

  .spotlight {
    position: absolute;
    border-radius: var(--gr-radius-md);
    box-shadow:
      0 0 0 9999px rgba(0, 0, 0, 0.45),
      0 0 0 2px var(--ksd-accent-color);
    background: transparent;
    pointer-events: none;
    transition: all 0.25s ease;
  }

  .card {
    position: absolute;
    width: 340px;
    max-width: calc(100vw - 32px);
    padding: var(--gr-space-md);
    background: var(--ksd-card-bg-color);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-md);
    box-shadow: var(--gr-shadow-lg);
    pointer-events: auto;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-xs);
  }

  .badge {
    align-self: flex-start;
    padding: 1px var(--gr-space-xs);
    font-size: 0.7rem;
    font-weight: 700;
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
  }

  .title {
    margin: 0;
    font-size: 1.05rem;
    font-weight: 700;
  }

  .body {
    margin: 0;
    font-size: 0.875rem;
    line-height: 1.5;
    color: var(--ksd-text-secondary-color);
  }

  .controls {
    display: flex;
    align-items: center;
    gap: var(--gr-space-2xs);
    margin-top: var(--gr-space-2xs);
  }

  .btn,
  .btnGhost,
  .btnPrimary {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border-radius: var(--gr-radius-sm);
    font-size: 0.8rem;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid var(--ksd-border-color);
    background: transparent;
    color: var(--ksd-text-main-color);

    &:disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }
  }

  .btnGhost {
    margin-left: auto;
    border-color: transparent;
    color: var(--ksd-text-secondary-color);
  }

  .btnPrimary {
    background: var(--ksd-accent-color);
    border-color: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
  }
</style>
