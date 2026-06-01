<script setup lang="ts">
  import { computed, onBeforeUnmount, ref } from "vue";
  import { useRouter } from "vue-router";
  import { useI18n } from "vue-i18n";

  import { useAskWizard } from "@/composables/use-ask-wizard";
  import { useQueryDelta } from "@/composables/use-query-delta";
  import { useApi } from "@/lib/api-client";
  import type { ExpertResult, MoEResult } from "@/entities/api";
  import { streamSSE, type SSEHandle } from "@/lib/sse";
  import ErrorBanner from "@/components/molecules/ErrorBanner/ErrorBanner.vue";

  const { t } = useI18n();
  const wizard = useAskWizard();
  const queryDelta = useQueryDelta();
  const router = useRouter();
  const api = useApi();

  // §2.2 — "Show on graph" lights evidence, dims complement. Additive CTA;
  // back-nav + chat-affordance untouched (evidence rides a useState bridge,
  // not the URL). MoE: fetch a delta per variant so each compare pane has
  // its own evidence.
  const showingDelta = ref(false);
  // §2.5 — store the RAW thrown error so ErrorBanner can read .status.
  const deltaErrorRaw = ref<unknown>(null);

  async function showOnGraph() {
    const variantIds = wizard.data.value.variant_ids;
    if (!variantIds.length) return;
    showingDelta.value = true;
    deltaErrorRaw.value = null;
    // Fresh ask → clear any stale highlight first.
    queryDelta.clear();
    try {
      const body = {
        mode: wizard.data.value.mode,
        query: wizard.data.value.query,
        variant_ids: variantIds,
        reasoner: wizard.data.value.reasoner,
        aggregator: wizard.data.value.aggregator,
        reasoner_params: wizard.data.value.reasoner_params,
        aggregator_params: wizard.data.value.aggregator_params,
      };
      if (wizard.data.value.mode === "moe") {
        // One delta call carrying every variant's evidence; the response
        // is keyed by variant_id so each pane reads its own.
        const resp = await api.reason.delta(body);
        queryDelta.setFromResponse(resp);
        await router.push(
          `/graphs/compare?ids=${variantIds.join(",")}&queryDelta=1`,
        );
      } else {
        const resp = await api.reason.delta({ ...body, variant_ids: variantIds });
        queryDelta.setFromResponse(resp);
        await router.push(`/graphs/${resp.variant_id}?queryDelta=1`);
      }
    } catch (e) {
      deltaErrorRaw.value = e;
    } finally {
      showingDelta.value = false;
    }
  }

  let handle: SSEHandle | undefined;
  const handleRef = ref<SSEHandle | null>(null);

  function stop() {
    handle?.cancel();
    handle = undefined;
    handleRef.value = null;
    wizard.streaming.value.running = false;
  }

  onBeforeUnmount(stop);

  async function ask() {
    if (handle) handle.cancel();

    wizard.streaming.value = {
      running: true,
      experts: [],
      answer: null,
      error: null,
    };

    handle = streamSSE(
      api.reason.streamUrl(),
      {
        method: "POST",
        body: JSON.stringify({
          mode: wizard.data.value.mode,
          query: wizard.data.value.query,
          variant_ids: wizard.data.value.variant_ids,
          reasoner: wizard.data.value.reasoner,
          aggregator: wizard.data.value.aggregator,
          reasoner_params: wizard.data.value.reasoner_params,
          aggregator_params: wizard.data.value.aggregator_params,
        }),
      },
      {
        onEvent(event, data) {
          if (event === "expert" && data && typeof data === "object") {
            wizard.streaming.value.experts = [
              ...wizard.streaming.value.experts,
              data as ExpertResult,
            ];
          } else if (event === "answer" && data && typeof data === "object") {
            wizard.streaming.value.answer = data as MoEResult;
          } else if (event === "error") {
            wizard.streaming.value.error =
              typeof data === "object" && data && "message" in data
                ? String((data as { message: unknown }).message)
                : String(data ?? "stream error");
          }
        },
        onError(err) {
          wizard.streaming.value.error =
            err instanceof Error ? err.message : String(err);
        },
        onClose() {
          wizard.streaming.value.running = false;
        },
      },
    );
    handleRef.value = handle;
  }

  const variantLabel = (id: string) => id.slice(0, 8);

  const allDone = computed(
    () => !wizard.streaming.value.running && wizard.streaming.value.answer,
  );

  defineExpose({ ask, stop });
</script>

<template>
  <section :class="$style.step">
    <header :class="$style.header">
      <h2 :class="$style.title">{{ t("wizard.ask.resultsTitle") }}</h2>
      <div :class="$style.controls">
        <button
          v-if="!wizard.streaming.value.running"
          type="button"
          :class="$style.cta"
          :disabled="!wizard.data.value.query.trim()"
          @click="ask"
        >
          {{ wizard.streaming.value.answer ? t("wizard.ask.askAgain") : t("wizard.ask.ask") }}
        </button>
        <button
          v-else
          type="button"
          :class="$style.stop"
          @click="stop"
        >
          {{ t("wizard.ask.stop") }}
        </button>
      </div>
    </header>

    <p :class="$style.queryEcho">
      <strong>Q:</strong> {{ wizard.data.value.query || "—" }}
    </p>

    <ErrorBanner
      v-if="wizard.streaming.value.error"
      :error="wizard.streaming.value.error"
    />

    <div :class="$style.experts">
      <h3 :class="$style.subhead">
        {{ t("wizard.ask.experts") }}
        <span :class="$style.muted" v-if="wizard.streaming.value.running">
          {{ t("wizard.ask.streamingChip") }}
        </span>
      </h3>
      <ul :class="$style.expertCards">
        <li
          v-for="(e, i) in wizard.streaming.value.experts"
          :key="i"
          :class="[$style.expertCard, e.error ? $style.expertCard_failed : '']"
        >
          <header :class="$style.expertHeader">
            <code>{{ e.reasoner }}</code>
            <span :class="$style.muted">@ {{ variantLabel(e.variant_id) }}</span>
            <span :class="$style.confidenceChip">
              conf {{ e.result.confidence?.toFixed(2) ?? "?" }}
            </span>
          </header>
          <p v-if="e.error" :class="$style.errText">FAILED: {{ e.error }}</p>
          <p v-else :class="$style.expertText">{{ e.result.text }}</p>
          <p :class="$style.muted" v-if="e.result.evidence_node_ids.length">
            evidence: {{ e.result.evidence_node_ids.length }}
            {{ t("wizard.ask.expertEvidenceSuffix") }}
          </p>
        </li>
      </ul>
      <p v-if="!wizard.streaming.value.experts.length" :class="$style.muted">
        {{ t("wizard.ask.askToStart") }}
      </p>
    </div>

    <div v-if="wizard.streaming.value.answer" :class="$style.answer">
      <h3 :class="$style.subhead">
        {{ t("wizard.ask.finalAnswer") }}
        <span :class="$style.muted">
          (aggregator: {{ wizard.streaming.value.answer.aggregator }})
        </span>
      </h3>
      <p :class="$style.answerText">
        {{ wizard.streaming.value.answer.answer.text }}
      </p>
      <dl :class="$style.answerMeta">
        <div>
          <dt>{{ t("wizard.ask.confidenceLabel") }}</dt>
          <dd>{{ wizard.streaming.value.answer.answer.confidence?.toFixed(2) ?? "—" }}</dd>
        </div>
        <div>
          <dt>{{ t("wizard.ask.evidenceNodesLabel") }}</dt>
          <dd>{{ wizard.streaming.value.answer.answer.evidence_node_ids.length }}</dd>
        </div>
        <div>
          <dt>Cost tokens</dt>
          <dd>{{ wizard.streaming.value.answer.answer.cost_tokens || "—" }}</dd>
        </div>
      </dl>
    </div>

    <div v-if="wizard.streaming.value.answer" :class="$style.graphCta">
      <button
        type="button"
        :class="$style.showGraphBtn"
        :disabled="showingDelta"
        @click="showOnGraph"
      >
        {{ showingDelta ? t("wizard.ask.showingOnGraph") : t("wizard.ask.showOnGraph") }}
      </button>
      <div v-if="deltaErrorRaw" data-testid="results-error">
        <ErrorBanner :error="deltaErrorRaw" />
      </div>
    </div>

    <div v-if="allDone && wizard.data.value.mode === 'moe'" :class="$style.compareCta">
      <NuxtLink
        :to="`/graphs/compare?ids=${wizard.data.value.variant_ids.join(',')}`"
        :class="$style.compareBtn"
      >
        {{ t("wizard.ask.openCompare") }}
      </NuxtLink>
    </div>
  </section>
</template>

<style lang="scss" module>
  .step {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-md);
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--gr-space-md);
  }

  .title {
    margin: 0;
    font-size: 1.25rem;
    font-weight: 600;
  }

  .controls {
    display: flex;
    gap: var(--gr-space-2xs);
  }

  .cta {
    padding: var(--gr-space-sm) var(--gr-space-xl);
    background: var(--gr-status-success);
    color: white;
    border: none;
    border-radius: var(--gr-radius-sm);
    font-weight: 600;
    cursor: pointer;

    &:hover:not(:disabled) {
      filter: brightness(1.05);
    }

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }

  .stop {
    padding: var(--gr-space-sm) var(--gr-space-lg);
    background: transparent;
    border: 1px solid var(--gr-status-failed);
    color: var(--gr-status-failed);
    border-radius: var(--gr-radius-sm);
    cursor: pointer;
  }

  .queryEcho {
    margin: 0;
    padding: var(--gr-space-sm);
    background: var(--ksd-card-bg-color);
    border-radius: var(--gr-radius-sm);
    font-style: italic;
  }

  .error {
    padding: var(--gr-space-sm);
    border: 1px solid var(--gr-status-failed);
    background: rgba(239, 68, 68, 0.08);
    border-radius: var(--gr-radius-sm);
  }

  .subhead {
    margin: 0 0 var(--gr-space-xs);
    font-size: 1rem;
    font-weight: 600;
  }

  .muted {
    color: var(--ksd-text-secondary-color);
    font-size: 0.875rem;
    font-weight: 400;
  }

  .expertCards {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: var(--gr-space-sm);
  }

  .expertCard {
    padding: var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
  }

  .expertCard_failed {
    border-color: var(--gr-status-failed);
    background: rgba(239, 68, 68, 0.05);
  }

  .expertHeader {
    display: flex;
    align-items: center;
    gap: var(--gr-space-2xs);
    margin-bottom: var(--gr-space-2xs);
  }

  .expertText {
    margin: 0 0 var(--gr-space-2xs);
    white-space: pre-wrap;
    font-size: 0.875rem;
    line-height: 1.4;
  }

  .errText {
    margin: 0;
    color: var(--gr-status-failed);
  }

  .confidenceChip {
    margin-left: auto;
    padding: 1px var(--gr-space-2xs);
    background: var(--ksd-card-bg-color);
    border-radius: var(--gr-radius-sm);
    font-size: 0.75rem;
    color: var(--ksd-text-secondary-color);
  }

  .answer {
    padding: var(--gr-space-md);
    border: 2px solid var(--ksd-accent-color);
    border-radius: var(--gr-radius-md);
    background: rgba(31, 119, 180, 0.05);
  }

  .answerText {
    white-space: pre-wrap;
    margin: 0 0 var(--gr-space-sm);
    line-height: 1.5;
  }

  .answerMeta {
    margin: 0;
    display: flex;
    gap: var(--gr-space-lg);

    dt {
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--ksd-text-secondary-color);
    }

    dd {
      margin: 0;
      font-weight: 600;
    }
  }

  .graphCta {
    display: flex;
    align-items: center;
    gap: var(--gr-space-sm);
  }

  .showGraphBtn {
    padding: var(--gr-space-sm) var(--gr-space-lg);
    background: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
    border: none;
    border-radius: var(--gr-radius-sm);
    font-weight: 600;
    cursor: pointer;

    &:hover:not(:disabled) {
      filter: brightness(1.05);
    }

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }

  .compareCta {
    text-align: right;
  }

  .compareBtn {
    color: var(--ksd-accent-color);
    font-weight: 600;
  }
</style>
