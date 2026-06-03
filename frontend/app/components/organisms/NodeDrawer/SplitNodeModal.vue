<script setup lang="ts">
  // N-way node split with per-provenance + per-edge routing.
  //
  // Backend contract (api/curation/ops.py:SplitNodePayload): one
  // `new_nodes: list[dict]` and `edge_redirect: dict[edge_id, new_id]`.
  // Edges absent from the map default to the first new node. We start
  // every branch's slot as "0" (first branch) and offer a smart
  // suggestion based on provenance-document overlap so the operator
  // doesn't have to route every edge by hand.

  import { computed, onMounted, ref, useTemplateRef, watch } from "vue";
  import { useI18n } from "vue-i18n";

  import type {
    Edge,
    GraphVariant,
    Id,
    Node,
    Provenance,
  } from "@/entities/api";
  import ErrorBanner from "@/components/molecules/ErrorBanner/ErrorBanner.vue";
  import type { EditCascade } from "@/composables/use-edit-cascade";

  type Props = {
    node: Node;
    variant: GraphVariant;
    actor: string;
    cascade: EditCascade;
    allEdges?: Edge[];
  };

  const props = withDefaults(defineProps<Props>(), {
    allEdges: () => [],
  });
  const emit = defineEmits<{
    (e: "close"): void;
    (e: "done", variant: GraphVariant): void;
  }>();
  const { t } = useI18n();

  // Client-minted UUIDs per branch — the applier honours new_nodes[i].id
  // when present (api/curation/applier.py:_new_split_ids), so we can
  // build a real edge_redirect map {edge_id: branch_uuid} instead of
  // sending {} and letting every edge fall through to the first branch.
  function mintId(): string {
    // crypto.randomUUID exists in all modern browsers + Node 19+.
    const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
    if (c?.randomUUID) return c.randomUUID();
    // Cheap fallback for unusual environments — not cryptographic, but
    // collision-resistant enough for a transient client-minted id that
    // the backend re-uses verbatim.
    return "br-" + Math.floor(Math.random() * 1e12).toString(16) + Date.now().toString(16);
  }
  const branchIds = ref<string[]>([mintId(), mintId()]);
  const branchNames = ref<string[]>([props.node.name, ""]);
  // Provenance index → branch index. Default all to 0 so flipping is
  // additive ("move this snippet to a new branch").
  const provAssignment = ref<number[]>(
    (props.node.provenance ?? []).map(() => 0),
  );
  // edgeId → branch index. Initially populated by smart default;
  // user-edited entries override.
  const edgeAssignment = ref<Record<string, number>>({});
  const saving = ref(false);
  const errorRaw = ref<unknown>(null);

  const name0Input = useTemplateRef<HTMLInputElement>("name0Input");
  onMounted(() => {
    name0Input.value?.focus();
  });

  const provenance = computed<Provenance[]>(
    () => props.node.provenance ?? [],
  );

  // Edges incident to the original node — these are the edges that the
  // applier needs to redirect.
  const incidentEdges = computed<Edge[]>(() => {
    const id = props.node.id;
    return (props.allEdges ?? []).filter(
      (e) => e.source_node_id === id || e.target_node_id === id,
    );
  });

  // For each branch index, the set of document ids assigned to it via
  // provenance. Used by the smart edge-routing default below.
  const branchDocSets = computed<Set<Id>[]>(() => {
    const sets: Set<Id>[] = branchNames.value.map(() => new Set<Id>());
    for (const [i, b] of provAssignment.value.entries()) {
      const p = provenance.value[i];
      if (!p) continue;
      const bag = sets[b];
      if (bag) bag.add(p.document_id);
    }
    return sets;
  });

  function smartBranchForEdge(e: Edge): number {
    const provs = e.provenance ?? [];
    if (!provs.length) return 0;
    const edocs = new Set(provs.map((p) => p.document_id));
    let bestBranch = 0;
    let bestOverlap = -1;
    branchDocSets.value.forEach((set, i) => {
      let overlap = 0;
      for (const d of edocs) if (set.has(d)) overlap += 1;
      if (overlap > bestOverlap) {
        bestOverlap = overlap;
        bestBranch = i;
      }
    });
    return bestBranch;
  }

  // Re-seed edgeAssignment when incident edges or branch doc sets change,
  // but DON'T overwrite entries the user already touched. We track that
  // via the "touched" flag — initial entries get false; explicit selects
  // flip it to true.
  const edgeTouched = ref<Record<string, boolean>>({});
  function seedEdgeAssignments() {
    for (const e of incidentEdges.value) {
      const key = String(e.id);
      if (edgeTouched.value[key]) continue;
      edgeAssignment.value[key] = smartBranchForEdge(e);
    }
  }
  watch(
    [incidentEdges, branchDocSets, branchNames],
    () => {
      // Clamp any out-of-range assignments after a branch removal.
      const n = branchNames.value.length;
      for (const k of Object.keys(edgeAssignment.value)) {
        if (edgeAssignment.value[k] >= n) edgeAssignment.value[k] = 0;
      }
      seedEdgeAssignments();
    },
    { immediate: true, deep: true },
  );

  function pickEdgeBranch(edgeId: Id, branch: number) {
    edgeAssignment.value[String(edgeId)] = branch;
    edgeTouched.value[String(edgeId)] = true;
  }

  function addBranch() {
    branchNames.value.push("");
    branchIds.value.push(mintId());
  }

  function removeBranch(idx: number) {
    if (branchNames.value.length <= 2) return;
    branchNames.value.splice(idx, 1);
    branchIds.value.splice(idx, 1);
    // Move any provenance assigned to the removed branch back to branch 0.
    for (let i = 0; i < provAssignment.value.length; i++) {
      if (provAssignment.value[i] === idx) provAssignment.value[i] = 0;
      else if (provAssignment.value[i] > idx) provAssignment.value[i] -= 1;
    }
    // Same for edges, and shift down everything past `idx`.
    for (const k of Object.keys(edgeAssignment.value)) {
      const cur = edgeAssignment.value[k];
      if (cur === idx) {
        edgeAssignment.value[k] = 0;
        edgeTouched.value[k] = false;
      } else if (cur > idx) {
        edgeAssignment.value[k] = cur - 1;
      }
    }
  }

  const provCountByBranch = computed<number[]>(() => {
    const counts = branchNames.value.map(() => 0);
    for (const b of provAssignment.value) {
      if (b < counts.length) counts[b] += 1;
    }
    return counts;
  });

  const edgeCountByBranch = computed<number[]>(() => {
    const counts = branchNames.value.map(() => 0);
    for (const e of incidentEdges.value) {
      const b = edgeAssignment.value[String(e.id)] ?? 0;
      if (b < counts.length) counts[b] += 1;
    }
    return counts;
  });

  const canSave = computed(() => {
    if (saving.value) return false;
    const names = branchNames.value.map((n) => n.trim());
    if (names.some((n) => !n)) return false;
    const unique = new Set(names);
    if (unique.size !== names.length) return false;
    return true;
  });

  function partitionProv(branchIdx: number): Provenance[] {
    const out: Provenance[] = [];
    for (const [i, p] of provenance.value.entries()) {
      if (provAssignment.value[i] === branchIdx) out.push(p);
    }
    return out;
  }

  function buildEdgeRedirect(): Record<string, string> {
    // edge_id → branch UUID. Backend uses these verbatim as the new
    // source / target replacement for the original node. Skip entries
    // that point to branch 0 since the applier already falls back there
    // (keeps wire-format small for the common case).
    const out: Record<string, string> = {};
    for (const e of incidentEdges.value) {
      const branch = edgeAssignment.value[String(e.id)] ?? 0;
      if (branch === 0) continue;
      const id = branchIds.value[branch];
      if (id) out[String(e.id)] = id;
    }
    return out;
  }

  async function submit() {
    if (!canSave.value) return;
    saving.value = true;
    errorRaw.value = null;
    try {
      const base = {
        graph_variant_id: props.variant.id,
        layer: props.node.layer,
        type: props.node.type,
        granularity: props.node.granularity,
        summary: props.node.summary,
        attributes: props.node.attributes ?? {},
      };
      const new_nodes = branchNames.value.map((name, i) => ({
        ...base,
        id: branchIds.value[i],
        name: name.trim(),
        provenance: partitionProv(i),
      }));
      const result = await props.cascade.append({
        op: "split_node",
        payload: {
          original_id: props.node.id,
          new_nodes,
          edge_redirect: buildEdgeRedirect(),
        },
        expected_version: props.variant.version,
        actor: props.actor,
      });
      emit("done", result.variant);
    } catch (e) {
      errorRaw.value = e;
    } finally {
      saving.value = false;
    }
  }

  function shortSpan(p: Provenance): string {
    return `${p.span_start}–${p.span_end}`;
  }
  function shortId(id: Id): string {
    return String(id).slice(0, 8);
  }
</script>

<template>
  <div :class="$style.backdrop" data-testid="split-modal" @click.self="emit('close')">
    <div :class="$style.modal" role="dialog" aria-modal="true">
      <header :class="$style.header">
        <h2 :class="$style.title">{{ t("node.splitTitle") }}</h2>
        <button
          type="button"
          :class="$style.close"
          :aria-label="t('node.splitCancel')"
          @click="emit('close')"
        >
          ×
        </button>
      </header>

      <p :class="$style.muted">{{ t("node.splitHintN") }}</p>

      <form :class="$style.body" @submit.prevent="submit">
        <fieldset :class="$style.fieldset">
          <legend :class="$style.subhead">
            {{ t("node.splitBranchesTitle") }}
            <span :class="$style.muted">({{ branchNames.length }})</span>
          </legend>
          <div :class="$style.branchList">
            <div
              v-for="(_, idx) in branchNames"
              :key="idx"
              :class="$style.branchRow"
            >
              <span :class="$style.branchBadge">{{ idx + 1 }}</span>
              <input
                v-if="idx === 0"
                ref="name0Input"
                v-model="branchNames[idx]"
                type="text"
                :disabled="saving"
                :class="$style.input"
                :placeholder="t('node.splitBranchName')"
              />
              <input
                v-else
                v-model="branchNames[idx]"
                type="text"
                :disabled="saving"
                :class="$style.input"
                :placeholder="t('node.splitBranchName')"
              />
              <span :class="$style.countChip" :title="t('node.splitProvCount')">
                P {{ provCountByBranch[idx] }}
              </span>
              <span :class="$style.countChip" :title="t('node.splitEdgeCount')">
                E {{ edgeCountByBranch[idx] }}
              </span>
              <button
                type="button"
                :class="$style.removeBtn"
                :disabled="saving || branchNames.length <= 2"
                :aria-label="t('node.splitBranchRemove')"
                :title="t('node.splitBranchRemove')"
                @click="removeBranch(idx)"
              >
                ×
              </button>
            </div>
          </div>
          <button
            type="button"
            :class="$style.addBtn"
            :disabled="saving"
            @click="addBranch"
          >
            + {{ t("node.splitBranchAdd") }}
          </button>
        </fieldset>

        <fieldset v-if="provenance.length" :class="$style.fieldset">
          <legend :class="$style.subhead">
            {{ t("node.splitProvenanceTitle") }}
            <span :class="$style.muted">({{ provenance.length }})</span>
          </legend>
          <ul :class="$style.itemList">
            <li
              v-for="(p, i) in provenance"
              :key="`${p.document_id}:${p.span_start}:${p.span_end}:${i}`"
              :class="$style.itemRow"
            >
              <span :class="$style.itemInfo">
                <code :class="$style.muted">{{ shortSpan(p) }}</code>
                <span :class="$style.muted" :title="p.document_id">
                  doc {{ shortId(p.document_id) }}…
                </span>
              </span>
              <select
                v-model.number="provAssignment[i]"
                :disabled="saving"
                :class="$style.select"
              >
                <option
                  v-for="(name, b) in branchNames"
                  :key="b"
                  :value="b"
                >
                  {{ b + 1 }} · {{ name.trim() || t("node.splitBranchUnnamed") }}
                </option>
              </select>
            </li>
          </ul>
        </fieldset>
        <p v-else :class="$style.muted">{{ t("node.splitNoProvenance") }}</p>

        <fieldset v-if="incidentEdges.length" :class="$style.fieldset">
          <legend :class="$style.subhead">
            {{ t("node.splitEdgesTitle") }}
            <span :class="$style.muted">({{ incidentEdges.length }})</span>
          </legend>
          <p :class="$style.warn">{{ t("node.splitEdgeRedirectNote") }}</p>
          <ul :class="$style.itemList">
            <li
              v-for="e in incidentEdges"
              :key="e.id"
              :class="$style.itemRow"
            >
              <span :class="$style.itemInfo">
                <span :class="$style.muted">{{ e.type }}</span>
                <code :class="$style.muted">{{ shortId(e.id) }}…</code>
              </span>
              <select
                :value="edgeAssignment[String(e.id)] ?? 0"
                :disabled="saving"
                :class="$style.select"
                @change="pickEdgeBranch(e.id, Number(($event.target as HTMLSelectElement).value))"
              >
                <option
                  v-for="(name, b) in branchNames"
                  :key="b"
                  :value="b"
                >
                  {{ b + 1 }} · {{ name.trim() || t("node.splitBranchUnnamed") }}
                </option>
              </select>
            </li>
          </ul>
        </fieldset>

        <ErrorBanner v-if="errorRaw" :error="errorRaw" />

        <div :class="$style.footer">
          <button
            type="button"
            :class="$style.btn"
            :disabled="saving"
            @click="emit('close')"
          >
            {{ t("node.splitCancel") }}
          </button>
          <button
            type="submit"
            data-testid="split-submit"
            :class="[$style.btn, $style.btn_primary]"
            :disabled="!canSave"
          >
            {{ saving ? "…" : t("node.splitConfirm") }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<style lang="scss" module>
  .backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 200;
    padding: var(--gr-space-md);
  }
  .modal {
    background: var(--ksd-card-bg-color);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-md);
    box-shadow: var(--gr-shadow-lg);
    width: 640px;
    max-width: 100%;
    max-height: calc(100vh - var(--gr-space-md) * 2);
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-sm);
    padding: var(--gr-space-md);
    overflow: hidden;
  }
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .title {
    margin: 0;
    font-size: 1.1rem;
    font-weight: 600;
  }
  .close {
    background: transparent;
    border: none;
    color: var(--ksd-text-secondary-color);
    cursor: pointer;
    font-size: 1.5rem;
    line-height: 1;
  }
  .muted {
    color: var(--ksd-text-secondary-color);
    font-size: 0.875rem;
    display: inline-flex;
    align-items: center;
    gap: var(--gr-space-2xs);
  }
  .warn {
    margin: 0;
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border-left: 3px solid var(--gr-status-warn);
    background: var(--ksd-bg-color);
    font-size: 0.8rem;
    color: var(--ksd-text-main-color);
  }
  .body {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-sm);
    overflow-y: auto;
  }
  .fieldset {
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    padding: var(--gr-space-xs);
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-xs);
  }
  .subhead {
    font-size: 0.95rem;
    font-weight: 600;
    padding: 0 var(--gr-space-2xs);
  }
  .branchList {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
  }
  .branchRow {
    display: grid;
    grid-template-columns: auto 1fr auto auto auto;
    gap: var(--gr-space-2xs);
    align-items: center;
  }
  .branchBadge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
    font-size: 0.8rem;
    font-weight: 600;
  }
  .countChip {
    padding: 0 var(--gr-space-2xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: 999px;
    font-size: 0.7rem;
    color: var(--ksd-text-main-color);
    font-variant-numeric: tabular-nums;
  }
  .removeBtn {
    background: transparent;
    border: 1px solid var(--ksd-border-color);
    color: var(--ksd-text-secondary-color);
    cursor: pointer;
    width: 24px;
    height: 24px;
    border-radius: var(--gr-radius-sm);
    line-height: 1;

    &:hover:not(:disabled) {
      border-color: var(--gr-status-failed);
      color: var(--gr-status-failed);
    }

    &:disabled {
      opacity: 0.3;
      cursor: not-allowed;
    }
  }
  .addBtn {
    align-self: flex-start;
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border: 1px dashed var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    color: var(--ksd-text-main-color);
    font-size: 0.875rem;
    cursor: pointer;

    &:hover:not(:disabled) {
      border-color: var(--ksd-accent-color);
      color: var(--ksd-accent-color);
    }
  }
  .input {
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
    font-size: 0.95rem;

    &:focus {
      outline: none;
      border-color: var(--ksd-accent-color);
    }
  }
  .select {
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
    font-size: 0.875rem;
    min-width: 0;
  }
  .itemList {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
    max-height: 220px;
    overflow-y: auto;
  }
  .itemRow {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: var(--gr-space-xs);
    align-items: center;
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border-bottom: 1px dashed var(--ksd-border-color);
    font-size: 0.85rem;
  }
  .itemInfo {
    display: flex;
    gap: var(--gr-space-xs);
    align-items: baseline;
    min-width: 0;
  }
  .footer {
    display: flex;
    justify-content: flex-end;
    gap: var(--gr-space-2xs);
  }
  .btn,
  .btn_primary {
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
    color: var(--ksd-bg-color);
    border-color: var(--ksd-accent-color);
  }
</style>
