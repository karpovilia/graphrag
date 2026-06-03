<script setup lang="ts">
  import { onMounted, ref } from "vue";
  import { useI18n } from "vue-i18n";

  import type { GraphVariant, MoEResult } from "@/entities/api";
  import { useApi } from "@/lib/api-client";
  import { useAskWizard } from "@/composables/use-ask-wizard";
  import ErrorBanner from "@/components/molecules/ErrorBanner/ErrorBanner.vue";
  import RagConfigGear from "@/components/organisms/AskWizard/RagConfigGear.vue";

  type Props = { variant: GraphVariant };
  const props = defineProps<Props>();
  const emit = defineEmits<{
    (e: "close"): void;
    (e: "highlight", nodeIds: string[]): void;
  }>();

  const { t } = useI18n();
  const api = useApi();
  // Strategy (reasoner/aggregator/params) lives in the shared ask-wizard state
  // so the config gear + saved configs work here too. Query is local.
  const wizard = useAskWizard();

  type HistoryItem = {
    query: string;
    reasoner: string;
    ts: number;
    answer: string;
    evidence: string[];
  };
  const HISTORY_KEY = "gr:rag-history";

  const running = ref(false);
  const result = ref<MoEResult | null>(null);
  const errorRaw = ref<unknown>(null);
  const history = ref<HistoryItem[]>([]);
  const showHistory = ref(false);

  function loadHistory() {
    try {
      history.value = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? "[]");
    } catch {
      history.value = [];
    }
  }
  function pushHistory(item: HistoryItem) {
    history.value = [item, ...history.value].slice(0, 50);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history.value));
  }

  onMounted(() => {
    loadHistory();
    if (!wizard.data.value.reasoner) wizard.data.value.reasoner = "lightrag_dual_keyword";
    if (!wizard.data.value.aggregator) wizard.data.value.aggregator = "evidence_union";
  });

  async function ask() {
    const query = wizard.data.value.query.trim();
    if (!query || running.value) return;
    running.value = true;
    errorRaw.value = null;
    try {
      const d = wizard.data.value;
      const res = await api.reason.run({
        mode: "single",
        variant_ids: [props.variant.id],
        reasoner: d.reasoner,
        aggregator: d.aggregator,
        query,
        reasoner_params: d.reasoner_params,
        aggregator_params: d.aggregator_params,
      });
      result.value = res;
      const evidence = (res.answer.evidence_node_ids ?? []).map(String);
      pushHistory({
        query,
        reasoner: d.reasoner,
        ts: Date.now(),
        answer: res.answer.text ?? "",
        evidence,
      });
      if (evidence.length) emit("highlight", evidence); // lineage → nodes on graph
    } catch (e) {
      errorRaw.value = e;
    } finally {
      running.value = false;
    }
  }

  function showOnGraph() {
    const ev = (result.value?.answer.evidence_node_ids ?? []).map(String);
    if (ev.length) emit("highlight", ev);
  }

  function revisit(item: HistoryItem) {
    wizard.data.value.query = item.query;
    showHistory.value = false;
    if (item.evidence.length) emit("highlight", item.evidence);
  }

  function onKeydown(e: KeyboardEvent) {
    if ((e.key === "Enter" && (e.metaKey || e.ctrlKey)) || (e.key === "Enter" && !e.shiftKey)) {
      e.preventDefault();
      void ask();
    }
  }
</script>

<template>
  <aside :class="$style.panel" data-testid="rag-dialog" aria-label="RAG dialog">
    <header :class="$style.head">
      <h3 :class="$style.title">{{ t("rag.title") }}</h3>
      <div :class="$style.headActions">
        <button
          type="button"
          :class="[$style.iconBtn, showHistory ? $style.iconBtn_active : '']"
          data-testid="rag-history-toggle"
          :title="t('rag.history')"
          @click="showHistory = !showHistory"
        >
          🕘
        </button>
        <RagConfigGear />
        <button type="button" :class="$style.iconBtn" data-testid="rag-close" @click="emit('close')">
          ×
        </button>
      </div>
    </header>

    <!-- history drawer -->
    <div v-if="showHistory" :class="$style.history" data-testid="rag-history">
      <p v-if="!history.length" :class="$style.muted">{{ t("rag.historyEmpty") }}</p>
      <button
        v-for="(h, i) in history"
        :key="i"
        type="button"
        :class="$style.historyItem"
        @click="revisit(h)"
      >
        <span :class="$style.historyQuery">{{ h.query }}</span>
        <span :class="$style.muted">{{ h.reasoner }}</span>
      </button>
    </div>

    <template v-else>
      <div :class="$style.strategyLine">
        <strong>{{ wizard.data.value.reasoner }}</strong> ·
        <strong>{{ wizard.data.value.aggregator }}</strong>
      </div>
      <textarea
        v-model="wizard.data.value.query"
        :class="$style.input"
        rows="3"
        data-testid="rag-input"
        :placeholder="t('rag.placeholder')"
        @keydown="onKeydown"
      />
      <button
        type="button"
        :class="$style.ask"
        data-testid="rag-ask"
        :disabled="running || !wizard.data.value.query.trim()"
        @click="ask"
      >
        {{ running ? t("rag.asking") : t("rag.ask") }}
      </button>

      <ErrorBanner v-if="errorRaw" :error="errorRaw" />

      <div v-if="result" :class="$style.answer" data-testid="rag-answer">
        <p :class="$style.answerText">{{ result.answer.text }}</p>
        <div :class="$style.answerMeta">
          <span v-if="result.answer.confidence != null" :class="$style.muted">
            conf {{ result.answer.confidence.toFixed(2) }}
          </span>
          <button
            v-if="result.answer.evidence_node_ids.length"
            type="button"
            :class="$style.showGraph"
            data-testid="rag-show-graph"
            @click="showOnGraph"
          >
            {{ t("rag.showOnGraph", { n: result.answer.evidence_node_ids.length }) }}
          </button>
        </div>
      </div>
    </template>
  </aside>
</template>

<style module>
  .panel {
    display: flex;
    flex-direction: column;
    width: 380px;
    max-width: 100%;
    height: 100%;
    border-left: 1px solid var(--ksd-border-color);
    background: var(--ksd-bg-color);
  }
  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--gr-space-sm);
    padding: var(--gr-space-sm);
    border-bottom: 1px solid var(--ksd-border-color);
  }
  .title {
    margin: 0;
    font-size: 0.95rem;
  }
  .headActions {
    display: flex;
    align-items: center;
    gap: var(--gr-space-2xs);
  }
  .iconBtn {
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    color: var(--ksd-text-main-color);
    cursor: pointer;
    font-size: 0.95rem;
    line-height: 1;
    padding: 3px 6px;

    &:hover {
      border-color: var(--ksd-accent-color);
    }
  }
  .iconBtn_active {
    border-color: var(--ksd-accent-color);
    color: var(--ksd-accent-color);
  }
  .strategyLine {
    padding: var(--gr-space-xs) var(--gr-space-sm) 0;
    font-size: 0.8125rem;
    color: var(--ksd-text-secondary-color, var(--ksd-text-main-color));
  }
  .input {
    margin: var(--gr-space-xs) var(--gr-space-sm) 0;
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
    font-family: inherit;
    font-size: 0.875rem;
    resize: vertical;
  }
  .ask {
    margin: var(--gr-space-xs) var(--gr-space-sm);
    padding: var(--gr-space-2xs) var(--gr-space-md);
    border: none;
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-accent-color);
    color: #fff;
    cursor: pointer;
    font-size: 0.875rem;
    align-self: flex-start;

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }
  .answer {
    margin: 0 var(--gr-space-sm) var(--gr-space-sm);
    padding: var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    overflow-y: auto;
  }
  .answerText {
    margin: 0;
    font-size: 0.875rem;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .answerMeta {
    display: flex;
    align-items: center;
    gap: var(--gr-space-sm);
    margin-top: var(--gr-space-xs);
  }
  .showGraph {
    border: 1px solid var(--ksd-accent-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    color: var(--ksd-accent-color);
    cursor: pointer;
    font-size: 0.75rem;
    padding: 2px var(--gr-space-xs);

    &:hover {
      background: var(--ksd-accent-color);
      color: #fff;
    }
  }
  .history {
    flex: 1;
    overflow-y: auto;
    padding: var(--gr-space-sm);
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
  }
  .historyItem {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 1px;
    text-align: left;
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    color: var(--ksd-text-main-color);
    cursor: pointer;

    &:hover {
      border-color: var(--ksd-accent-color);
    }
  }
  .historyQuery {
    font-size: 0.85rem;
  }
  .muted {
    font-size: 0.75rem;
    color: var(--ksd-text-secondary-color, var(--ksd-text-main-color));
    opacity: 0.85;
  }
</style>
