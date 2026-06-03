<script setup lang="ts">
  import { useAsyncData } from "nuxt/app";
  import { computed, nextTick, ref, useTemplateRef, watch } from "vue";
  import { useI18n } from "vue-i18n";

  import type {
    Edge,
    GraphVariant,
    Id,
    Node,
    Provenance,
    StrategyDescriptor,
    ToolInvocation,
  } from "@/entities/api";
  import { useApi } from "@/lib/api-client";
  import { formatRelativeTime } from "@/lib/format";
  import ErrorBanner from "@/components/molecules/ErrorBanner/ErrorBanner.vue";
  import LatencyBadge from "@/components/molecules/LatencyBadge/LatencyBadge.vue";
  import { useEditCascade, type EditCascade } from "@/composables/use-edit-cascade";
  import SplitNodeModal from "./SplitNodeModal.vue";

  type Props = {
    node: Node;
    variant: GraphVariant;
    actor?: string;
    /** §2.3 — the page lifts ONE cascade and passes it down so the ripple
     * paints the shared LayeredGraph. Falls back to an owned instance. */
    cascade?: EditCascade;
    /** Full node list from the host page — used by the merge picker so we
     * don't refetch /api/graphs/{id}/nodes per drawer mount. */
    allNodes?: Node[];
    /** Full edge list — passed to SplitNodeModal so it can show the
     * incident edges and let the operator route each one to a branch. */
    allEdges?: Edge[];
  };

  const props = withDefaults(defineProps<Props>(), {
    actor: "user:ui",
    allNodes: () => [],
    allEdges: () => [],
  });
  const emit = defineEmits<{
    (e: "close"): void;
    (e: "variant-changed", variant: GraphVariant): void;
  }>();
  const { t } = useI18n();
  const api = useApi();

  const cascade = props.cascade ?? useEditCascade(props.variant.id);

  const variantId = computed(() => props.variant.id);

  // Documents in the host corpus — used to resolve provenance.document_id
  // to a human-readable title in the Sources section. Refetched only when
  // the corpus changes; same instance is reused across node selections.
  const corpusIdRef = computed(() => props.variant.corpus_id);
  const { data: corpusDocs } = await useAsyncData(
    () => `corpus-docs:${corpusIdRef.value}`,
    () => api.corpora.listDocuments(corpusIdRef.value),
    { watch: [corpusIdRef], default: () => [] },
  );

  const { data: tools, refresh: refreshTools } = await useAsyncData(
    () => `tools:${variantId.value}:${props.node.id}`,
    () => api.nodes.listTools(variantId.value, props.node.id),
    { watch: [() => props.node.id] },
  );

  const { data: history, refresh: refreshHistory } = await useAsyncData(
    () => `tool-history:${variantId.value}:${props.node.id}`,
    () => api.nodes.listToolInvocations(variantId.value, props.node.id),
    { watch: [() => props.node.id] },
  );

  watch(
    () => props.node.id,
    () => {
      refreshTools();
      refreshHistory();
      // Reset edit/merge UI when the user picks a different node.
      editing.value = false;
      renameErrorRaw.value = null;
      summaryEditing.value = false;
      summaryErrorRaw.value = null;
      mergePickerOpen.value = false;
      mergeQuery.value = "";
      mergeErrorRaw.value = null;
      splitOpen.value = false;
    },
  );

  const running = ref<string | null>(null);
  const lastResult = ref<ToolInvocation | null>(null);
  // §2.5 — store the RAW thrown error so ErrorBanner can read .status.
  const toolErrorRaw = ref<unknown>(null);

  // ---- rename ----
  const editing = ref(false);
  const draftName = ref("");
  const renameSaving = ref(false);
  const renameErrorRaw = ref<unknown>(null);
  const renameInput = useTemplateRef<HTMLInputElement>("renameInput");

  async function startRename() {
    draftName.value = props.node.name;
    renameErrorRaw.value = null;
    editing.value = true;
    await nextTick();
    renameInput.value?.focus();
    renameInput.value?.select();
  }

  function cancelRename() {
    editing.value = false;
    renameErrorRaw.value = null;
  }

  // ---- summary edit ----
  const summaryEditing = ref(false);
  const summaryDraft = ref("");
  const summarySaving = ref(false);
  const summaryErrorRaw = ref<unknown>(null);
  // Resummarize uses the LLM endpoint to generate a draft into the
  // editor; the operator saves explicitly via the same Save button so
  // one user gesture = one journal entry.
  const resummarizing = ref(false);
  const resummarizeMeta = ref<{ model: string; snippetCount: number } | null>(
    null,
  );

  async function resummarize() {
    if (resummarizing.value) return;
    resummarizing.value = true;
    summaryErrorRaw.value = null;
    resummarizeMeta.value = null;
    try {
      const out = await api.nodes.resummarize(
        props.variant.id,
        props.node.id,
      );
      if (!summaryEditing.value) {
        summaryDraft.value = out.summary;
        summaryEditing.value = true;
      } else {
        summaryDraft.value = out.summary;
      }
      resummarizeMeta.value = {
        model: out.model,
        snippetCount: out.snippet_count,
      };
    } catch (e) {
      summaryErrorRaw.value = e;
    } finally {
      resummarizing.value = false;
    }
  }

  function startSummaryEdit() {
    summaryDraft.value = props.node.summary ?? "";
    summaryErrorRaw.value = null;
    summaryEditing.value = true;
  }

  function cancelSummaryEdit() {
    summaryEditing.value = false;
    summaryErrorRaw.value = null;
  }

  async function saveSummary() {
    const next = summaryDraft.value.trim();
    const prev = props.node.summary ?? "";
    if (next === prev) {
      summaryEditing.value = false;
      return;
    }
    summarySaving.value = true;
    summaryErrorRaw.value = null;
    try {
      const result = await cascade.append({
        op: "set_summary",
        payload: { node_id: props.node.id, summary: next || null },
        expected_version: props.variant.version,
        actor: props.actor,
      });
      emit("variant-changed", result.variant);
      summaryEditing.value = false;
    } catch (e) {
      summaryErrorRaw.value = e;
    } finally {
      summarySaving.value = false;
    }
  }

  // ---- sources (provenance) ----
  type SourceGroup = {
    docId: Id;
    title: string;
    spans: Provenance[];
    count: number;
  };
  const sourceGroups = computed<SourceGroup[]>(() => {
    const provs = props.node.provenance ?? [];
    if (!provs.length) return [];
    const byDoc = new Map<Id, Provenance[]>();
    for (const p of provs) {
      const list = byDoc.get(p.document_id);
      if (list) list.push(p);
      else byDoc.set(p.document_id, [p]);
    }
    const titleById = new Map<Id, string>(
      (corpusDocs.value ?? []).map((d) => [d.id, d.title]),
    );
    return [...byDoc.entries()]
      .map(([docId, spans]) => ({
        docId,
        title: titleById.get(docId) ?? `doc ${String(docId).slice(0, 8)}…`,
        spans,
        count: spans.length,
      }))
      .sort((a, b) => b.count - a.count);
  });

  // ---- merge picker ----
  const mergePickerOpen = ref(false);
  const mergeQuery = ref("");
  const mergeSaving = ref(false);
  const mergeErrorRaw = ref<unknown>(null);

  const mergeCandidates = computed<Node[]>(() => {
    const q = mergeQuery.value.trim().toLowerCase();
    const self = props.node.id;
    const layer = props.node.layer;
    return (props.allNodes ?? [])
      .filter((n) => n.id !== self && n.layer === layer)
      .filter((n) =>
        q ? (n.name ?? "").toLowerCase().includes(q) : true,
      )
      .slice(0, 8);
  });

  function startMerge() {
    mergePickerOpen.value = true;
    mergeQuery.value = "";
    mergeErrorRaw.value = null;
  }

  function cancelMerge() {
    mergePickerOpen.value = false;
    mergeErrorRaw.value = null;
  }

  async function confirmMerge(absorbed: Node) {
    mergeSaving.value = true;
    mergeErrorRaw.value = null;
    try {
      const result = await cascade.append({
        op: "merge_nodes",
        payload: {
          survivor_id: props.node.id,
          absorbed_ids: [absorbed.id],
          reason: `merged via UI: '${absorbed.name}' → '${props.node.name}'`,
        },
        expected_version: props.variant.version,
        actor: props.actor,
      });
      emit("variant-changed", result.variant);
      mergePickerOpen.value = false;
      mergeQuery.value = "";
    } catch (e) {
      mergeErrorRaw.value = e;
    } finally {
      mergeSaving.value = false;
    }
  }

  // ---- split ----
  const splitOpen = ref(false);
  function openSplit() {
    splitOpen.value = true;
  }
  function closeSplit() {
    splitOpen.value = false;
  }
  function onSplitDone(variant: GraphVariant) {
    emit("variant-changed", variant);
    splitOpen.value = false;
  }

  async function saveRename() {
    const trimmed = draftName.value.trim();
    if (!trimmed || trimmed === props.node.name) {
      editing.value = false;
      return;
    }
    renameSaving.value = true;
    renameErrorRaw.value = null;
    try {
      // §2.3 — route through the cascade so the rename gets the ripple +
      // latency badge, then emit the unchanged variant-changed contract.
      const result = await cascade.append({
        op: "update_node_name",
        payload: { node_id: props.node.id, name: trimmed },
        expected_version: props.variant.version,
        actor: props.actor,
      });
      emit("variant-changed", result.variant);
      editing.value = false;
    } catch (e) {
      renameErrorRaw.value = e;
    } finally {
      renameSaving.value = false;
    }
  }

  async function run(tool: StrategyDescriptor) {
    running.value = tool.name;
    toolErrorRaw.value = null;
    try {
      const inv = await api.nodes.runTool(
        variantId.value,
        props.node.id,
        tool.name,
        {},
      );
      lastResult.value = inv;
      await refreshHistory();
    } catch (e) {
      toolErrorRaw.value = e;
    } finally {
      running.value = null;
    }
  }

  // §2.5 read-only temporal-history visibility — node bitemporal stamps.
  const hasTemporal = computed(
    () =>
      props.node.valid_from != null ||
      props.node.valid_to != null ||
      props.node.tx_from != null ||
      props.node.tx_to != null,
  );

  function fmtStamp(iso: string | null | undefined): string {
    if (!iso) return "—";
    return formatRelativeTime(iso);
  }

  const sorted = computed(() => {
    const universals = (tools.value ?? []).filter((t) => {
      // applies_to lives on the class, not the descriptor; we infer by
      // looking at the cost_hint+name pair. Cheap heuristic — wizard
      // can later request `?include=class` if we need exact data.
      return true;
    });
    return universals;
  });
</script>

<template>
  <aside :class="$style.drawer" data-testid="node-drawer" aria-label="Node detail panel">
    <header :class="$style.header">
      <div :class="$style.titleRow">
        <template v-if="!editing">
          <strong :class="$style.title">{{ node.name }}</strong>
          <button
            type="button"
            data-testid="node-rename"
            :class="$style.iconBtn"
            :title="t('node.rename')"
            :aria-label="t('node.rename')"
            @click="startRename"
          >
            ✎
          </button>
        </template>
        <form
          v-else
          :class="$style.renameForm"
          @submit.prevent="saveRename"
        >
          <input
            ref="renameInput"
            v-model="draftName"
            type="text"
            :class="$style.renameInput"
            :aria-label="t('node.renameTitle')"
            :disabled="renameSaving"
            @keydown.escape.prevent="cancelRename"
          />
          <button
            type="submit"
            data-testid="node-rename-save"
            :class="$style.renameSave"
            :disabled="renameSaving || !draftName.trim()"
          >
            {{ renameSaving ? "…" : t("node.renameSave") }}
          </button>
          <button
            type="button"
            data-testid="node-rename-cancel"
            :class="$style.renameCancel"
            :disabled="renameSaving"
            @click="cancelRename"
          >
            {{ t("node.renameCancel") }}
          </button>
        </form>
        <button
          v-if="!editing"
          type="button"
          :class="$style.close"
          @click="emit('close')"
        >
          ×
        </button>
      </div>
      <LatencyBadge
        v-if="cascade.lastTiming.value"
        :ms="cascade.lastTiming.value.recompute_ms"
        :node-count="cascade.lastTiming.value.node_count_after"
        :edge-count="cascade.lastTiming.value.edge_count_after"
      />
      <ErrorBanner v-if="renameErrorRaw" :error="renameErrorRaw">
        <template #action>
          <button type="button" :class="$style.iconBtn" @click="startRename">
            {{ t("node.rename") }}
          </button>
        </template>
      </ErrorBanner>
      <div :class="$style.meta">
        <span :class="[$style.chip, $style[`chip_${node.layer}`] || '']">
          {{ node.layer }}
        </span>
        <span :class="$style.chip_type">{{ node.type }}</span>
        <span :class="$style.muted" :title="node.id">
          id {{ node.id.slice(0, 8) }}
        </span>
      </div>
    </header>

    <section :class="$style.summary">
      <h3 :class="$style.subhead">
        Summary
        <button
          v-if="!summaryEditing"
          type="button"
          data-testid="node-summary-edit"
          :class="$style.iconBtn"
          :title="t('node.summaryEdit')"
          :aria-label="t('node.summaryEdit')"
          @click="startSummaryEdit"
        >
          ✎
        </button>
        <button
          type="button"
          data-testid="node-summary-resummarize"
          :class="$style.iconBtn"
          :title="t('node.summaryResummarize')"
          :aria-label="t('node.summaryResummarize')"
          :disabled="resummarizing || (node.provenance?.length ?? 0) === 0"
          @click="resummarize"
        >
          {{ resummarizing ? "…" : "✨" }}
        </button>
      </h3>
      <p v-if="resummarizeMeta" :class="$style.muted">
        {{ t("node.summaryResummarizeMeta", {
          model: resummarizeMeta.model,
          n: resummarizeMeta.snippetCount,
        }) }}
      </p>
      <p v-if="!summaryEditing && node.summary">{{ node.summary }}</p>
      <p v-else-if="!summaryEditing" :class="$style.muted">
        {{ t("node.summaryEmpty") }}
      </p>
      <form
        v-else
        :class="$style.summaryForm"
        @submit.prevent="saveSummary"
      >
        <textarea
          v-model="summaryDraft"
          :class="$style.summaryTextarea"
          :rows="6"
          :disabled="summarySaving"
          @keydown.escape.prevent="cancelSummaryEdit"
        />
        <div :class="$style.formActions">
          <button
            type="submit"
            data-testid="node-summary-save"
            :class="$style.renameSave"
            :disabled="summarySaving"
          >
            {{ summarySaving ? "…" : t("node.summarySave") }}
          </button>
          <button
            type="button"
            data-testid="node-summary-cancel"
            :class="$style.renameCancel"
            :disabled="summarySaving"
            @click="cancelSummaryEdit"
          >
            {{ t("node.summaryCancel") }}
          </button>
        </div>
      </form>
      <ErrorBanner v-if="summaryErrorRaw" :error="summaryErrorRaw" />
    </section>

    <section v-if="sourceGroups.length" :class="$style.sources">
      <h3 :class="$style.subhead">
        {{ t("node.sourcesTitle") }}
        <span :class="$style.muted">({{ node.provenance.length }})</span>
      </h3>
      <ul :class="$style.sourceList">
        <li
          v-for="s in sourceGroups"
          :key="s.docId"
          :class="$style.sourceRow"
        >
          <NuxtLink
            :to="`/corpora/${variant.corpus_id}/documents/${s.docId}`"
            :class="$style.sourceLink"
            :title="s.title"
          >
            <strong :class="$style.sourceTitle">{{ s.title }}</strong>
            <span :class="$style.muted">×{{ s.count }}</span>
          </NuxtLink>
        </li>
      </ul>
    </section>

    <section :class="$style.curation">
      <h3 :class="$style.subhead">{{ t("node.curationTitle") }}</h3>
      <div :class="$style.curationRow">
        <button
          v-if="!mergePickerOpen"
          type="button"
          data-testid="node-merge-open"
          :class="$style.curationBtn"
          @click="startMerge"
        >
          {{ t("node.mergeAction") }}
        </button>
        <button
          type="button"
          data-testid="node-split-open"
          :class="$style.curationBtn"
          :disabled="splitOpen"
          @click="openSplit"
        >
          {{ t("node.splitAction") }}
        </button>
      </div>

      <div v-if="mergePickerOpen" :class="$style.mergeBox">
        <input
          v-model="mergeQuery"
          type="search"
          :placeholder="t('node.mergeSearchPlaceholder')"
          :class="$style.mergeInput"
          :disabled="mergeSaving"
        />
        <ul :class="$style.mergeList">
          <li v-if="!mergeCandidates.length" :class="$style.muted">
            {{ t("node.mergeNoResults") }}
          </li>
          <li
            v-for="cand in mergeCandidates"
            :key="cand.id"
          >
            <button
              type="button"
              data-testid="node-merge-pick"
              :class="$style.mergePick"
              :disabled="mergeSaving"
              @click="confirmMerge(cand)"
              :title="t('node.mergeConfirmHint', { name: cand.name })"
            >
              <strong>{{ cand.name }}</strong>
              <span :class="$style.muted">{{ cand.type }}</span>
            </button>
          </li>
        </ul>
        <div :class="$style.formActions">
          <button
            type="button"
            :class="$style.renameCancel"
            :disabled="mergeSaving"
            @click="cancelMerge"
          >
            {{ t("node.mergeCancel") }}
          </button>
        </div>
        <ErrorBanner v-if="mergeErrorRaw" :error="mergeErrorRaw" />
      </div>
    </section>

    <SplitNodeModal
      v-if="splitOpen"
      :node="node"
      :variant="variant"
      :actor="actor"
      :cascade="cascade"
      :all-edges="allEdges"
      @close="closeSplit"
      @done="onSplitDone"
    />

    <section
      v-if="hasTemporal"
      data-testid="temporal-history"
      :class="$style.temporal"
    >
      <h3 :class="$style.subhead">{{ t("temporal.title") }}</h3>
      <dl data-testid="temporal-valid" :class="$style.temporalRow">
        <dt :class="$style.muted">{{ t("temporal.validRange") }}</dt>
        <dd>
          {{ t("temporal.validFrom") }}: {{ fmtStamp(node.valid_from) }}
          →
          {{ node.valid_to ? fmtStamp(node.valid_to) : t("temporal.stillValid") }}
        </dd>
      </dl>
      <dl data-testid="temporal-tx" :class="$style.temporalRow">
        <dt :class="$style.muted">{{ t("temporal.txRange") }}</dt>
        <dd>
          {{ t("temporal.txFrom") }}: {{ fmtStamp(node.tx_from) }}
          →
          {{ node.tx_to ? fmtStamp(node.tx_to) : t("temporal.stillCurrent") }}
        </dd>
      </dl>
    </section>

    <section :class="$style.tools">
      <h3 :class="$style.subhead">
        Tools
        <span :class="$style.muted" v-if="tools">({{ tools.length }})</span>
      </h3>
      <ul :class="$style.toolList" v-if="(sorted ?? []).length">
        <li
          v-for="t in sorted"
          :key="t.name"
          :class="$style.toolRow"
        >
          <button
            type="button"
            :class="$style.toolBtn"
            :disabled="running !== null"
            @click="run(t)"
          >
            <strong>{{ t.name }}</strong>
            <span :class="$style.muted">{{ t.summary }}</span>
            <span :class="$style.toolMeta">
              <span :class="$style.costChip">{{ t.cost_hint ?? "?" }}</span>
              <span v-if="running === t.name">…</span>
              <span v-else>▶</span>
            </span>
          </button>
        </li>
      </ul>
      <p v-else :class="$style.muted">{{ t("node.noTools") }}</p>
    </section>

    <ErrorBanner v-if="toolErrorRaw" :error="toolErrorRaw" />

    <section v-if="lastResult" :class="$style.lastResult">
      <h3 :class="$style.subhead">{{ t("node.lastResult") }}</h3>
      <p :class="$style.muted">
        {{ lastResult.tool }} ·
        {{ formatRelativeTime(lastResult.created_at) }}
      </p>
      <pre :class="$style.json">{{ JSON.stringify(lastResult.result, null, 2) }}</pre>
    </section>

    <section v-if="(history ?? []).length" :class="$style.history">
      <h3 :class="$style.subhead">
        {{ t("node.history") }} ({{ history?.length ?? 0 }})
      </h3>
      <ul :class="$style.historyList">
        <li
          v-for="h in history ?? []"
          :key="h.id"
          :class="$style.historyRow"
        >
          <strong>{{ h.tool }}</strong>
          <span :class="$style.muted">{{ formatRelativeTime(h.created_at) }}</span>
        </li>
      </ul>
    </section>
  </aside>
</template>

<style lang="scss" module>
  .drawer {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-md);
    width: 380px;
    max-width: 100%;
    height: 100%;
    background: var(--ksd-card-bg-color);
    border-left: 1px solid var(--ksd-border-color);
    overflow-y: auto;
    padding: var(--gr-space-md);
    flex-shrink: 0;
  }

  .header {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-xs);
  }

  .titleRow {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: var(--gr-space-xs);
  }

  .title {
    font-size: 1.1rem;
    line-height: 1.3;
    word-break: break-word;
  }

  .close {
    background: transparent;
    border: none;
    color: var(--ksd-text-secondary-color);
    cursor: pointer;
    font-size: 1.5rem;
    line-height: 1;
    padding: 0;
    flex-shrink: 0;
  }

  .iconBtn {
    background: transparent;
    border: 1px solid var(--ksd-border-color);
    color: var(--ksd-text-secondary-color);
    cursor: pointer;
    font-size: 0.9rem;
    line-height: 1;
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border-radius: var(--gr-radius-sm);
    flex-shrink: 0;

    &:hover {
      border-color: var(--ksd-accent-color);
      color: var(--ksd-accent-color);
    }
  }

  .renameForm {
    display: flex;
    flex: 1;
    gap: var(--gr-space-2xs);
    align-items: center;
  }

  .renameInput {
    flex: 1;
    min-width: 0;
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border: 1px solid var(--ksd-accent-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
    font-size: 1rem;
    line-height: 1.3;
  }

  .renameSave,
  .renameCancel {
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border-radius: var(--gr-radius-sm);
    border: 1px solid var(--ksd-border-color);
    cursor: pointer;
    font-size: 0.8rem;
    background: transparent;
    color: var(--ksd-text-main-color);

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }

  .renameSave {
    background: var(--ksd-accent-color);
    border-color: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
  }

  .meta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gr-space-2xs);
    align-items: center;
  }

  .chip,
  .chip_type {
    padding: 2px var(--gr-space-xs);
    font-size: 0.75rem;
    border-radius: var(--gr-radius-sm);
    text-transform: lowercase;
  }

  .chip_chunk {
    background: var(--gr-layer-chunk);
    color: white;
  }
  .chip_entity {
    background: var(--gr-layer-entity);
    color: white;
  }
  .chip_community {
    background: var(--gr-layer-community);
    color: white;
  }
  .chip_topic {
    background: var(--gr-layer-topic);
    color: white;
  }

  .chip_type {
    background: var(--ksd-card-bg-color);
    border: 1px solid var(--ksd-border-color);
    color: var(--ksd-text-main-color);
  }

  .muted {
    color: var(--ksd-text-secondary-color);
    font-size: 0.875rem;
  }

  .summary p {
    margin: 0;
    white-space: pre-wrap;
    line-height: 1.5;
  }
  .summaryForm {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-xs);
  }
  .summaryTextarea {
    width: 100%;
    resize: vertical;
    padding: var(--gr-space-xs);
    border: 1px solid var(--ksd-accent-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
    font: inherit;
    line-height: 1.5;
  }
  .formActions {
    display: flex;
    gap: var(--gr-space-2xs);
  }

  .sources {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-xs);
  }
  .sourceList {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
    max-height: 220px;
    overflow-y: auto;
  }
  .sourceRow {
    display: contents;
  }
  .sourceLink {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--gr-space-xs);
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
    text-decoration: none;
    line-height: 1.3;

    &:hover {
      border-color: var(--ksd-accent-color);
    }
  }
  .sourceTitle {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
  }

  .curation {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-xs);
  }
  .curationRow {
    display: flex;
    gap: var(--gr-space-2xs);
    flex-wrap: wrap;
  }
  .curationBtn {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    color: var(--ksd-text-main-color);
    cursor: pointer;
    font-size: 0.875rem;

    &:hover:not(:disabled) {
      border-color: var(--ksd-accent-color);
      color: var(--ksd-accent-color);
    }

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }
  .mergeBox {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-xs);
    padding: var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
  }
  .mergeInput {
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
    font-size: 0.875rem;
  }
  .mergeList {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
    max-height: 220px;
    overflow-y: auto;
  }
  .mergePick {
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    color: var(--ksd-text-main-color);
    cursor: pointer;
    text-align: left;
    font-size: 0.875rem;

    &:hover:not(:disabled) {
      border-color: var(--ksd-accent-color);
    }

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }

  .temporal {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
  }

  .temporalRow {
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;

    dd {
      margin: 0;
      font-size: 0.8rem;
      font-variant-numeric: tabular-nums;
    }
  }

  .subhead {
    margin: 0 0 var(--gr-space-xs);
    font-size: 0.95rem;
    font-weight: 600;
    display: flex;
    align-items: baseline;
    gap: var(--gr-space-2xs);
  }

  .tools {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-xs);
  }

  .toolList {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
  }

  .toolRow {
    display: contents;
  }

  .toolBtn {
    display: flex;
    flex-direction: column;
    gap: 2px;
    align-items: flex-start;
    padding: var(--gr-space-xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    background: var(--ksd-bg-color);
    border-radius: var(--gr-radius-sm);
    color: var(--ksd-text-main-color);
    cursor: pointer;
    text-align: left;
    width: 100%;
    position: relative;

    &:hover:not(:disabled) {
      border-color: var(--ksd-accent-color);
    }

    &:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }
  }

  .toolMeta {
    position: absolute;
    right: var(--gr-space-xs);
    top: var(--gr-space-xs);
    display: flex;
    align-items: center;
    gap: var(--gr-space-2xs);
  }

  .costChip {
    font-size: 0.7rem;
    padding: 1px var(--gr-space-2xs);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-card-bg-color);
    color: var(--ksd-text-secondary-color);
    text-transform: uppercase;
  }

  .error {
    padding: var(--gr-space-xs);
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid var(--gr-status-failed);
    border-radius: var(--gr-radius-sm);
    color: var(--ksd-text-main-color);
    font-size: 0.875rem;
  }

  .lastResult,
  .history {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
  }

  .json {
    margin: 0;
    padding: var(--gr-space-xs);
    background: var(--ksd-bg-color);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    font-family: ui-monospace, monospace;
    font-size: 0.75rem;
    overflow-x: auto;
    max-height: 200px;
  }

  .historyList {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
  }

  .historyRow {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding: var(--gr-space-2xs) 0;
    border-bottom: 1px dashed var(--ksd-border-color);
    font-size: 0.875rem;
  }
</style>
