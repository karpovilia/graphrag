<script setup lang="ts">
  import { onMounted, ref } from "vue";
  import { useI18n } from "vue-i18n";

  import type { Citation, GraphVariant, Id, RagAnswer } from "@/entities/api";
  import { useApi } from "@/lib/api-client";
  import ErrorBanner from "@/components/molecules/ErrorBanner/ErrorBanner.vue";

  type Props = {
    variant: GraphVariant;
    /** End of the selected period (timeline scrubber). Temporal mode weights
     * nodes changed close to it higher. */
    asOf?: string;
  };
  const props = defineProps<Props>();
  const emit = defineEmits<{
    (e: "close"): void;
    (e: "highlight", nodeIds: string[]): void;
  }>();

  const { t } = useI18n();
  const api = useApi();

  // ---- config (graphs / depth / temporal), with save+switch presets ----
  const selectedVariantIds = ref<Id[]>([props.variant.id]);
  const topK = ref(15);
  const temporal = ref(false);
  const variants = ref<GraphVariant[]>([]);
  const showConfig = ref(false);

  type RagPreset = {
    name: string;
    variant_ids: Id[];
    top_k: number;
    temporal: boolean;
  };
  const PRESET_KEY = "gr:rag-configs";
  const presets = ref<RagPreset[]>([]);
  const newPresetName = ref("");

  function loadPresets() {
    try {
      presets.value = JSON.parse(localStorage.getItem(PRESET_KEY) ?? "[]");
    } catch {
      presets.value = [];
    }
  }
  function savePreset() {
    const name = newPresetName.value.trim();
    if (!name) return;
    const p: RagPreset = {
      name,
      variant_ids: [...selectedVariantIds.value],
      top_k: topK.value,
      temporal: temporal.value,
    };
    const i = presets.value.findIndex((x) => x.name === name);
    if (i >= 0) presets.value[i] = p;
    else presets.value.push(p);
    localStorage.setItem(PRESET_KEY, JSON.stringify(presets.value));
    newPresetName.value = "";
  }
  function applyPreset(p: RagPreset) {
    selectedVariantIds.value = [...p.variant_ids];
    topK.value = p.top_k;
    temporal.value = p.temporal;
  }
  function removePreset(name: string) {
    presets.value = presets.value.filter((x) => x.name !== name);
    localStorage.setItem(PRESET_KEY, JSON.stringify(presets.value));
  }
  function toggleVariant(id: Id) {
    const i = selectedVariantIds.value.indexOf(id);
    if (i >= 0) selectedVariantIds.value.splice(i, 1);
    else selectedVariantIds.value.push(id);
  }

  // ---- query / answer / history ----
  type HistoryItem = { query: string; ts: number; answer: string; evidence: string[] };
  const HISTORY_KEY = "gr:rag-history";
  const query = ref("");
  const running = ref(false);
  const result = ref<RagAnswer | null>(null);
  const citations = ref<Citation[]>([]);
  const chunkNodeIds = ref<string[]>([]);
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

  onMounted(async () => {
    loadPresets();
    loadHistory();
    try {
      variants.value = await api.graphs.list(props.variant.corpus_id);
    } catch {
      variants.value = [props.variant];
    }
  });

  async function ask() {
    const q = query.value.trim();
    if (!q || running.value) return;
    running.value = true;
    errorRaw.value = null;
    try {
      const res = await api.graphs.rag(props.variant.id, {
        query: q,
        variant_ids: selectedVariantIds.value,
        top_k_entities: topK.value,
        recency_boost: temporal.value ? 2.0 : 0,
        half_life_days: 30,
        as_of: temporal.value ? (props.asOf ?? "") : "",
      });
      result.value = res;
      citations.value = res.citations;
      chunkNodeIds.value = res.chunk_node_ids.map(String);
      const evidence = res.evidence_node_ids.map(String);
      history.value = [
        { query: q, ts: Date.now(), answer: res.answer, evidence },
        ...history.value,
      ].slice(0, 50);
      localStorage.setItem(HISTORY_KEY, JSON.stringify(history.value));
      if (evidence.length) emit("highlight", evidence);
    } catch (e) {
      errorRaw.value = e;
    } finally {
      running.value = false;
    }
  }

  function showEvidence() {
    const ev = (result.value?.evidence_node_ids ?? []).map(String);
    if (ev.length) emit("highlight", ev);
  }
  function showChunks() {
    if (chunkNodeIds.value.length) emit("highlight", chunkNodeIds.value);
  }
  function revisit(h: HistoryItem) {
    query.value = h.query;
    showHistory.value = false;
    if (h.evidence.length) emit("highlight", h.evidence);
  }
  function onKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
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
          @click="showHistory = !showHistory; showConfig = false"
        >
          🕘
        </button>
        <button
          type="button"
          :class="[$style.iconBtn, showConfig ? $style.iconBtn_active : '']"
          data-testid="rag-config-toggle"
          :title="t('rag.config')"
          @click="showConfig = !showConfig; showHistory = false"
        >
          ⚙
        </button>
        <button type="button" :class="$style.iconBtn" data-testid="rag-close" @click="emit('close')">
          ×
        </button>
      </div>
    </header>

    <!-- config panel -->
    <div v-if="showConfig" :class="$style.config" data-testid="rag-config">
      <div :class="$style.cfgBlock">
        <span :class="$style.cfgLabel">{{ t("rag.graphs") }}</span>
        <label v-for="v in variants" :key="v.id" :class="$style.cfgCheck">
          <input
            type="checkbox"
            :checked="selectedVariantIds.includes(v.id)"
            data-testid="rag-variant"
            @change="toggleVariant(v.id)"
          />
          {{ v.name }}
        </label>
        <p :class="$style.muted">
          {{ selectedVariantIds.length > 1 ? t("rag.modeMoe") : t("rag.modeSingle") }}
        </p>
      </div>
      <label :class="$style.cfgRow">
        <span :class="$style.cfgLabel">{{ t("rag.depth") }}</span>
        <input v-model.number="topK" type="number" min="1" max="50" :class="$style.num" />
      </label>
      <label :class="$style.cfgCheck">
        <input v-model="temporal" type="checkbox" data-testid="rag-temporal" />
        {{ t("rag.temporal") }}
        <span v-if="temporal && asOf" :class="$style.muted">· {{ asOf.slice(0, 10) }}</span>
      </label>

      <div :class="$style.presets">
        <button
          v-for="p in presets"
          :key="p.name"
          type="button"
          :class="$style.preset"
          @click="applyPreset(p)"
        >
          {{ p.name }}
          <span :class="$style.presetDel" @click.stop="removePreset(p.name)">×</span>
        </button>
      </div>
      <div :class="$style.saveRow">
        <input
          v-model="newPresetName"
          :class="$style.num"
          :placeholder="t('rag.presetName')"
          @keydown.enter.prevent="savePreset"
        />
        <button type="button" :class="$style.smallBtn" :disabled="!newPresetName.trim()" @click="savePreset">
          {{ t("rag.savePreset") }}
        </button>
      </div>
    </div>

    <!-- history drawer -->
    <div v-else-if="showHistory" :class="$style.history" data-testid="rag-history">
      <p v-if="!history.length" :class="$style.muted">{{ t("rag.historyEmpty") }}</p>
      <button v-for="(h, i) in history" :key="i" type="button" :class="$style.historyItem" @click="revisit(h)">
        <span :class="$style.historyQuery">{{ h.query }}</span>
        <span :class="$style.muted">{{ h.answer.slice(0, 80) }}</span>
      </button>
    </div>

    <template v-else>
      <textarea
        v-model="query"
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
        :disabled="running || !query.trim()"
        @click="ask"
      >
        {{ running ? t("rag.asking") : t("rag.ask") }}
      </button>

      <ErrorBanner v-if="errorRaw" :error="errorRaw" />

      <div v-if="result" :class="$style.answer" data-testid="rag-answer">
        <p :class="$style.answerText">{{ result.answer }}</p>
        <div :class="$style.answerMeta">
          <button
            v-if="result.evidence_node_ids.length"
            type="button"
            :class="$style.showGraph"
            data-testid="rag-show-graph"
            @click="showEvidence"
          >
            {{ t("rag.showOnGraph", { n: result.evidence_node_ids.length }) }}
          </button>
          <button
            v-if="chunkNodeIds.length"
            type="button"
            :class="$style.showGraph"
            data-testid="rag-show-chunks"
            @click="showChunks"
          >
            {{ t("rag.showChunks", { n: chunkNodeIds.length }) }}
          </button>
        </div>

        <div v-if="citations.length" :class="$style.citations" data-testid="rag-citations">
          <h4 :class="$style.citTitle">{{ t("rag.citations") }}</h4>
          <ol :class="$style.citList">
            <li v-for="(c, i) in citations" :key="i" :class="$style.cit">
              <span :class="$style.citMeta">
                [{{ i + 1 }}] {{ c.document_title || "—" }}<template v-if="c.valid_from"> · {{ c.valid_from.slice(0, 10) }}</template>
              </span>
              <span :class="$style.citText">{{ c.snippet }}</span>
            </li>
          </ol>
        </div>
      </div>
    </template>
  </aside>
</template>

<style module>
  .panel {
    display: flex;
    flex-direction: column;
    width: 400px;
    max-width: 100%;
    height: 100%;
    border-left: 1px solid var(--ksd-border-color);
    background: var(--ksd-bg-color);
    overflow-y: auto;
  }
  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--gr-space-sm);
    padding: var(--gr-space-sm);
    border-bottom: 1px solid var(--ksd-border-color);
    position: sticky;
    top: 0;
    background: var(--ksd-bg-color);
    z-index: 1;
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
    font-size: 1.1rem;
    line-height: 1;
    padding: 4px 8px;

    &:hover {
      border-color: var(--ksd-accent-color);
    }
  }
  .iconBtn_active {
    border-color: var(--ksd-accent-color);
    color: var(--ksd-accent-color);
  }
  .config {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-sm);
    padding: var(--gr-space-sm);
    border-bottom: 1px solid var(--ksd-border-color);
  }
  .cfgBlock {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .cfgLabel {
    font-size: 0.8rem;
    font-weight: 600;
  }
  .cfgRow {
    display: flex;
    align-items: center;
    gap: var(--gr-space-xs);
  }
  .cfgCheck {
    display: flex;
    align-items: center;
    gap: var(--gr-space-2xs);
    font-size: 0.85rem;
    cursor: pointer;
  }
  .num {
    width: 5rem;
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
    font-size: 0.8125rem;
  }
  .presets {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gr-space-2xs);
  }
  .preset {
    display: flex;
    align-items: center;
    gap: var(--gr-space-2xs);
    padding: 2px var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    color: var(--ksd-text-main-color);
    cursor: pointer;
    font-size: 0.8rem;

    &:hover {
      border-color: var(--ksd-accent-color);
    }
  }
  .presetDel {
    color: var(--ksd-text-secondary-color);
    &:hover {
      color: var(--ksd-danger-color, #c0392b);
    }
  }
  .saveRow {
    display: flex;
    gap: var(--gr-space-2xs);
  }
  .smallBtn {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border: none;
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-accent-color);
    color: #fff;
    cursor: pointer;
    font-size: 0.8rem;

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }
  .input {
    margin: var(--gr-space-sm) var(--gr-space-sm) 0;
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
  }
  .answerText {
    margin: 0;
    font-size: 0.9rem;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .answerMeta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gr-space-xs);
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
  .citations {
    margin-top: var(--gr-space-sm);
    border-top: 1px solid var(--ksd-border-color);
    padding-top: var(--gr-space-xs);
  }
  .citTitle {
    margin: 0 0 var(--gr-space-2xs);
    font-size: 0.8rem;
  }
  .citList {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
  }
  .cit {
    font-size: 0.78rem;
  }
  .citMeta {
    display: block;
    color: var(--ksd-accent-color);
    font-variant-numeric: tabular-nums;
  }
  .citText {
    display: block;
    color: var(--ksd-text-main-color);
    white-space: pre-wrap;
    word-break: break-word;
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
    margin: 0;
    font-size: 0.75rem;
    color: var(--ksd-text-secondary-color, var(--ksd-text-main-color));
    opacity: 0.85;
  }
</style>
