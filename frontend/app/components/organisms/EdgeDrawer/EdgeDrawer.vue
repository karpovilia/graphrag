<script setup lang="ts">
  // Edge-side counterpart to NodeDrawer. Backend curation ops EditEdge +
  // DeleteEdge already exist; this is the missing UI that turns
  // `selectedLink` into something the user can read and act on. Mirrors
  // the NodeDrawer layout (header → meta → editable explanation →
  // sources → actions) so the right panel feels uniform whether you
  // clicked a node or an edge.

  import { useAsyncData } from "nuxt/app";
  import { computed, ref, watch } from "vue";
  import { useI18n } from "vue-i18n";

  import type {
    Edge,
    GraphVariant,
    Id,
    Node,
    Provenance,
  } from "@/entities/api";
  import { useApi } from "@/lib/api-client";
  import ErrorBanner from "@/components/molecules/ErrorBanner/ErrorBanner.vue";
  import LatencyBadge from "@/components/molecules/LatencyBadge/LatencyBadge.vue";
  import { useEditCascade, type EditCascade } from "@/composables/use-edit-cascade";

  type Props = {
    edge: Edge;
    variant: GraphVariant;
    actor?: string;
    cascade?: EditCascade;
    /** Pass-through from the host page so we can resolve
     * source_node_id / target_node_id to human-readable names without a
     * round-trip. */
    allNodes?: Node[];
  };

  const props = withDefaults(defineProps<Props>(), {
    actor: "user:ui",
    cascade: undefined,
    allNodes: () => [],
  });
  const emit = defineEmits<{
    (e: "close"): void;
    (e: "variant-changed", variant: GraphVariant): void;
    (e: "select-node", id: Id): void;
  }>();
  const { t } = useI18n();
  const api = useApi();

  const cascade = props.cascade ?? useEditCascade(props.variant.id);

  // ---- source/target node lookup ----
  const nodeById = computed(() => {
    const m = new Map<Id, Node>();
    for (const n of props.allNodes) m.set(n.id, n);
    return m;
  });
  const sourceNode = computed<Node | null>(
    () => nodeById.value.get(props.edge.source_node_id) ?? null,
  );
  const targetNode = computed<Node | null>(
    () => nodeById.value.get(props.edge.target_node_id) ?? null,
  );

  function shortName(n: Node | null, fallbackId: Id): string {
    if (n) return n.name;
    return `node ${String(fallbackId).slice(0, 8)}…`;
  }

  // ---- corpus documents for provenance link resolution ----
  const corpusIdRef = computed(() => props.variant.corpus_id);
  const { data: corpusDocs } = await useAsyncData(
    () => `corpus-docs:${corpusIdRef.value}`,
    () => api.corpora.listDocuments(corpusIdRef.value),
    { watch: [corpusIdRef], default: () => [] },
  );

  type SourceGroup = {
    docId: Id;
    title: string;
    spans: Provenance[];
    count: number;
  };
  const sourceGroups = computed<SourceGroup[]>(() => {
    const provs = props.edge.provenance ?? [];
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

  // ---- edit form (weight / relation / explanation) ----
  const editing = ref(false);
  const draftWeight = ref<string>("");
  const draftRelation = ref<string>("");
  const draftExplanation = ref<string>("");
  const saving = ref(false);
  const errorRaw = ref<unknown>(null);

  function startEdit() {
    draftWeight.value =
      props.edge.weight != null ? String(props.edge.weight) : "";
    draftRelation.value = props.edge.relation ?? "";
    draftExplanation.value = props.edge.explanation ?? "";
    errorRaw.value = null;
    editing.value = true;
  }

  function cancelEdit() {
    editing.value = false;
    errorRaw.value = null;
  }

  async function saveEdit() {
    saving.value = true;
    errorRaw.value = null;
    try {
      const updates: Record<string, unknown> = {};
      const w = draftWeight.value.trim();
      if (w === "") {
        if (props.edge.weight != null) updates.weight = null;
      } else {
        const num = Number(w);
        if (!Number.isFinite(num)) throw new Error(t("edge.editBadWeight"));
        if (num !== props.edge.weight) updates.weight = num;
      }
      const rel = draftRelation.value.trim();
      const prevRel = props.edge.relation ?? "";
      if (rel !== prevRel) updates.relation = rel || null;
      const expl = draftExplanation.value.trim();
      const prevExpl = props.edge.explanation ?? "";
      if (expl !== prevExpl) updates.explanation = expl || null;
      if (Object.keys(updates).length === 0) {
        editing.value = false;
        return;
      }
      const result = await cascade.append({
        op: "edit_edge",
        payload: { edge_id: props.edge.id, updates },
        expected_version: props.variant.version,
        actor: props.actor,
      });
      emit("variant-changed", result.variant);
      editing.value = false;
    } catch (e) {
      errorRaw.value = e;
    } finally {
      saving.value = false;
    }
  }

  // ---- delete ----
  const deleting = ref(false);
  const deleteConfirmOpen = ref(false);
  const deleteReason = ref("");
  const deleteErrorRaw = ref<unknown>(null);

  function startDelete() {
    deleteConfirmOpen.value = true;
    deleteReason.value = "";
    deleteErrorRaw.value = null;
  }

  function cancelDelete() {
    deleteConfirmOpen.value = false;
    deleteErrorRaw.value = null;
  }

  async function confirmDelete() {
    deleting.value = true;
    deleteErrorRaw.value = null;
    try {
      const result = await cascade.append({
        op: "delete_edge",
        payload: {
          edge_id: props.edge.id,
          reason: deleteReason.value.trim() || null,
        },
        expected_version: props.variant.version,
        actor: props.actor,
      });
      emit("variant-changed", result.variant);
      deleteConfirmOpen.value = false;
      emit("close");
    } catch (e) {
      deleteErrorRaw.value = e;
    } finally {
      deleting.value = false;
    }
  }

  watch(
    () => props.edge.id,
    () => {
      editing.value = false;
      deleteConfirmOpen.value = false;
      errorRaw.value = null;
      deleteErrorRaw.value = null;
    },
  );

  const hasTemporal = computed(
    () =>
      props.edge.valid_from != null
      || props.edge.valid_to != null
      || props.edge.tx_from != null
      || props.edge.tx_to != null,
  );
</script>

<template>
  <aside :class="$style.drawer" data-testid="edge-drawer" aria-label="Edge detail panel">
    <header :class="$style.header">
      <div :class="$style.titleRow">
        <strong :class="$style.title">
          <button
            type="button"
            :class="$style.endpointBtn"
            :title="t('edge.endpointHint')"
            @click="emit('select-node', edge.source_node_id)"
          >
            {{ shortName(sourceNode, edge.source_node_id) }}
          </button>
          <span :class="$style.muted">→</span>
          <button
            type="button"
            :class="$style.endpointBtn"
            :title="t('edge.endpointHint')"
            @click="emit('select-node', edge.target_node_id)"
          >
            {{ shortName(targetNode, edge.target_node_id) }}
          </button>
        </strong>
        <button
          type="button"
          :class="$style.close"
          :aria-label="t('edge.close')"
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
      <div :class="$style.meta">
        <span :class="$style.chip">{{ edge.type }}</span>
        <span
          v-if="edge.relation"
          :class="$style.chip_type"
        >{{ edge.relation }}</span>
        <span v-if="edge.weight != null" :class="$style.muted">
          weight {{ edge.weight.toFixed(3) }}
        </span>
        <span :class="$style.muted" :title="edge.id">
          id {{ edge.id.slice(0, 8) }}
        </span>
      </div>
    </header>

    <section v-if="!editing" :class="$style.summary">
      <h3 :class="$style.subhead">
        {{ t("edge.explanationTitle") }}
        <button
          type="button"
          data-testid="edge-edit-open"
          :class="$style.iconBtn"
          :title="t('edge.editAction')"
          @click="startEdit"
        >
          ✎
        </button>
      </h3>
      <p v-if="edge.explanation">{{ edge.explanation }}</p>
      <p v-else :class="$style.muted">{{ t("edge.explanationEmpty") }}</p>
    </section>
    <section v-else :class="$style.summary">
      <h3 :class="$style.subhead">{{ t("edge.editTitle") }}</h3>
      <form :class="$style.editForm" @submit.prevent="saveEdit">
        <label :class="$style.field">
          <span :class="$style.muted">{{ t("edge.fieldRelation") }}</span>
          <input
            v-model="draftRelation"
            type="text"
            :disabled="saving"
            :class="$style.input"
          />
        </label>
        <label :class="$style.field">
          <span :class="$style.muted">{{ t("edge.fieldWeight") }}</span>
          <input
            v-model="draftWeight"
            type="text"
            inputmode="decimal"
            :placeholder="t('edge.fieldWeightPlaceholder')"
            :disabled="saving"
            :class="$style.input"
          />
        </label>
        <label :class="$style.field">
          <span :class="$style.muted">{{ t("edge.fieldExplanation") }}</span>
          <textarea
            v-model="draftExplanation"
            :rows="4"
            :disabled="saving"
            :class="$style.textarea"
          />
        </label>
        <ErrorBanner v-if="errorRaw" :error="errorRaw" />
        <div :class="$style.formActions">
          <button
            type="submit"
            data-testid="edge-edit-save"
            :class="$style.btn_primary"
            :disabled="saving"
          >
            {{ saving ? "…" : t("edge.editSave") }}
          </button>
          <button
            type="button"
            :class="$style.btn"
            :disabled="saving"
            @click="cancelEdit"
          >
            {{ t("edge.editCancel") }}
          </button>
        </div>
      </form>
    </section>

    <section
      v-if="hasTemporal"
      data-testid="edge-temporal"
      :class="$style.temporal"
    >
      <h3 :class="$style.subhead">{{ t("temporal.title") }}</h3>
      <dl :class="$style.temporalRow">
        <dt :class="$style.muted">{{ t("temporal.validRange") }}</dt>
        <dd>
          {{ edge.valid_from ?? "—" }} → {{ edge.valid_to ?? t("temporal.stillValid") }}
        </dd>
      </dl>
      <dl :class="$style.temporalRow">
        <dt :class="$style.muted">{{ t("temporal.txRange") }}</dt>
        <dd>
          {{ edge.tx_from ?? "—" }} → {{ edge.tx_to ?? t("temporal.stillCurrent") }}
        </dd>
      </dl>
    </section>

    <section v-if="sourceGroups.length" :class="$style.sources">
      <h3 :class="$style.subhead">
        {{ t("edge.sourcesTitle") }}
        <span :class="$style.muted">({{ edge.provenance.length }})</span>
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
      <h3 :class="$style.subhead">{{ t("edge.curationTitle") }}</h3>
      <div v-if="!deleteConfirmOpen" :class="$style.curationRow">
        <button
          type="button"
          data-testid="edge-delete-open"
          :class="$style.btn_danger"
          @click="startDelete"
        >
          {{ t("edge.deleteAction") }}
        </button>
      </div>
      <div v-else :class="$style.deleteBox">
        <p :class="$style.muted">{{ t("edge.deleteConfirm") }}</p>
        <input
          v-model="deleteReason"
          type="text"
          :placeholder="t('edge.deleteReasonPlaceholder')"
          :disabled="deleting"
          :class="$style.input"
        />
        <ErrorBanner v-if="deleteErrorRaw" :error="deleteErrorRaw" />
        <div :class="$style.formActions">
          <button
            type="button"
            data-testid="edge-delete-confirm"
            :class="$style.btn_danger"
            :disabled="deleting"
            @click="confirmDelete"
          >
            {{ deleting ? "…" : t("edge.deleteConfirmButton") }}
          </button>
          <button
            type="button"
            :class="$style.btn"
            :disabled="deleting"
            @click="cancelDelete"
          >
            {{ t("edge.deleteCancel") }}
          </button>
        </div>
      </div>
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
    font-size: 1rem;
    line-height: 1.3;
    display: flex;
    flex-wrap: wrap;
    gap: var(--gr-space-2xs);
    align-items: baseline;
  }
  .endpointBtn {
    background: transparent;
    border: none;
    color: var(--ksd-text-main-color);
    cursor: pointer;
    font: inherit;
    padding: 0;
    text-decoration: underline dotted var(--ksd-text-secondary-color);

    &:hover {
      color: var(--ksd-accent-color);
    }
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

    &:hover {
      border-color: var(--ksd-accent-color);
      color: var(--ksd-accent-color);
    }
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
    background: var(--ksd-bg-color);
    border: 1px solid var(--ksd-border-color);
    color: var(--ksd-text-main-color);
  }
  .chip_type {
    background: var(--ksd-card-bg-color);
  }
  .muted {
    color: var(--ksd-text-secondary-color);
    font-size: 0.875rem;
  }
  .subhead {
    margin: 0 0 var(--gr-space-xs);
    font-size: 0.95rem;
    font-weight: 600;
    display: flex;
    align-items: baseline;
    gap: var(--gr-space-2xs);
  }
  .summary {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-xs);
  }
  .summary p {
    margin: 0;
    white-space: pre-wrap;
    line-height: 1.5;
  }
  .editForm {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-xs);
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
  }
  .input {
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
    font: inherit;

    &:focus {
      outline: none;
      border-color: var(--ksd-accent-color);
    }
  }
  .textarea {
    @extend .input;
    resize: vertical;
  }
  .formActions {
    display: flex;
    gap: var(--gr-space-2xs);
  }
  .btn,
  .btn_primary,
  .btn_danger {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    color: var(--ksd-text-main-color);
    cursor: pointer;
    font-size: 0.875rem;

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }
  .btn_primary {
    background: var(--ksd-accent-color);
    border-color: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
  }
  .btn_danger {
    border-color: var(--gr-status-failed);
    color: var(--gr-status-failed);

    &:hover:not(:disabled) {
      background: var(--gr-status-failed);
      color: white;
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
  .deleteBox {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-xs);
    padding: var(--gr-space-xs);
    border: 1px solid var(--gr-status-failed);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
  }
</style>
