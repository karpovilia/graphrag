<script setup lang="ts">
  // SchemaStep — wizard step 3.
  //
  // Sits between EDA and Pipeline. Asks the LLM for a domain-specific
  // ontology proposal (entity_types + typed relations with domain/range)
  // on a sample of the corpus, lets the user prune/edit, and PUT-s the
  // result to /api/corpora/{id}/schema so downstream extraction is
  // typed instead of dumping everything into PERSON/ORG/CONCEPT/MISC.
  //
  // UX commitments (memory: feedback_wizard_backnav):
  //   - Back-nav must keep the draft intact — state lives in the wizard
  //     composable, not in this component.
  //   - Skipping the step is allowed: the corpus stays without a schema
  //     and extraction falls back to open-vocab. The "Skip" button is
  //     explicit so the user knows what they're trading off.
  import { computed, ref, watch } from "vue";
  import { useI18n } from "vue-i18n";

  import { useBuildWizard } from "@/composables/use-build-wizard";
  import { useApi } from "@/lib/api-client";
  import type {
    CorpusSchema,
    EntityTypeDef,
    RelationTypeDef,
  } from "@/entities/api";

  const { t } = useI18n();
  const wizard = useBuildWizard();
  const api = useApi();

  const proposeSize = ref(25);
  const loading = ref(false);
  const saving = ref(false);
  const error = ref<string | null>(null);

  function emptySchema(): CorpusSchema {
    return { entity_types: [], relation_types: [], version: 0 };
  }

  // Always work with a local copy so back-nav preserves edits even when
  // the user hasn't saved yet.
  const draft = computed<CorpusSchema>({
    get: () => wizard.data.value.schema ?? emptySchema(),
    set: (v) => {
      wizard.data.value.schema = v;
    },
  });

  // Names already used as entity types — for domain/range chip pickers.
  const entityNames = computed<string[]>(() =>
    draft.value.entity_types.map((t) => t.name),
  );

  async function loadExisting() {
    if (!wizard.data.value.corpus_id) return;
    try {
      const existing = await api.corpora.getSchema(wizard.data.value.corpus_id);
      if (
        existing &&
        (existing.entity_types?.length || existing.relation_types?.length)
      ) {
        draft.value = existing;
      }
    } catch {
      // 404-style — nothing to hydrate.
    }
  }

  async function runPropose() {
    if (!wizard.data.value.corpus_id) {
      error.value = t("wizard.schema.errorNoCorpus");
      return;
    }
    error.value = null;
    loading.value = true;
    try {
      const proposed = await api.corpora.proposeSchema(
        wizard.data.value.corpus_id,
        { sample_size: proposeSize.value },
      );
      // Merge strategy: replace the draft outright. The user can prune
      // afterwards; persistent edits would compete with the LLM's
      // suggestions and confuse the diff.
      draft.value = proposed;
      wizard.invalidateDownstream(3);
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      loading.value = false;
    }
  }

  async function save() {
    if (!wizard.data.value.corpus_id) {
      error.value = t("wizard.schema.errorNoCorpus");
      return;
    }
    error.value = null;
    saving.value = true;
    try {
      const saved = await api.corpora.putSchema(
        wizard.data.value.corpus_id,
        draft.value,
      );
      draft.value = saved;
      wizard.markCompleted(3);
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      saving.value = false;
    }
  }

  function addEntityType() {
    draft.value = {
      ...draft.value,
      entity_types: [
        ...draft.value.entity_types,
        { name: "NEW_TYPE", description: "", examples: [] },
      ],
    };
  }

  function removeEntityType(idx: number) {
    const removed = draft.value.entity_types[idx]?.name;
    const newEntities = draft.value.entity_types.filter((_, i) => i !== idx);
    // Drop relations that referenced the removed type from domain/range,
    // and drop relations whose domain or range becomes empty (no point
    // keeping a triple with nowhere to live).
    const newRelations = draft.value.relation_types
      .map((r) => ({
        ...r,
        domain: removed ? r.domain.filter((d) => d !== removed) : r.domain,
        range: removed ? r.range.filter((d) => d !== removed) : r.range,
      }))
      .filter((r) => r.domain.length > 0 || r.range.length > 0 || true);
    // Keep all relations after the prune — even with an empty range the
    // user might want to re-tag it. The backend's `validate_triple` will
    // treat empty domain/range as "any" so we don't auto-delete.
    draft.value = {
      ...draft.value,
      entity_types: newEntities,
      relation_types: newRelations,
    };
  }

  function addRelationType() {
    draft.value = {
      ...draft.value,
      relation_types: [
        ...draft.value.relation_types,
        {
          name: "NEW_RELATION",
          description: "",
          domain: [],
          range: [],
          symmetric: false,
          examples: [],
        },
      ],
    };
  }

  function removeRelationType(idx: number) {
    draft.value = {
      ...draft.value,
      relation_types: draft.value.relation_types.filter((_, i) => i !== idx),
    };
  }

  function toggleInList(list: string[], name: string): string[] {
    return list.includes(name) ? list.filter((n) => n !== name) : [...list, name];
  }

  function updateEntity(idx: number, patch: Partial<EntityTypeDef>) {
    draft.value = {
      ...draft.value,
      entity_types: draft.value.entity_types.map((t, i) =>
        i === idx ? { ...t, ...patch } : t,
      ),
    };
  }

  function updateRelation(idx: number, patch: Partial<RelationTypeDef>) {
    draft.value = {
      ...draft.value,
      relation_types: draft.value.relation_types.map((r, i) =>
        i === idx ? { ...r, ...patch } : r,
      ),
    };
  }

  function examplesString(ex: string[]): string {
    return ex.join(", ");
  }
  function parseExamples(s: string): string[] {
    return s
      .split(",")
      .map((p) => p.trim())
      .filter(Boolean);
  }

  // Auto-load existing schema when the user lands on this step.
  watch(
    () => wizard.currentIndex.value,
    (idx) => {
      if (idx === 3 && draft.value.entity_types.length === 0) {
        loadExisting();
      }
    },
    { immediate: true },
  );

  function skip() {
    // Mark completed without saving so user can advance.
    wizard.markCompleted(3);
    wizard.next();
  }
</script>

<template>
  <section :class="$style.step">
    <h2 :class="$style.title">{{ t("wizard.schema.title") }}</h2>
    <p :class="$style.hint">{{ t("wizard.schema.hint") }}</p>

    <div :class="$style.proposeBar">
      <label :class="$style.sampleLabel">
        {{ t("wizard.schema.sampleSize") }}
        <input
          v-model.number="proposeSize"
          type="number"
          min="5"
          max="100"
          :class="$style.numberInput"
        >
      </label>
      <button
        type="button"
        :class="$style.proposeBtn"
        :disabled="loading || !wizard.data.value.corpus_id"
        @click="runPropose"
      >
        {{ loading ? t("wizard.schema.proposing") : t("wizard.schema.propose") }}
      </button>
      <button
        type="button"
        :class="$style.skipBtn"
        :disabled="saving"
        :title="t('wizard.schema.skipHint')"
        @click="skip"
      >
        {{ t("wizard.schema.skip") }}
      </button>
    </div>

    <div v-if="error" :class="$style.error">{{ error }}</div>

    <!-- Soft-schema disclaimer. Visible always so users don't ship a
         build expecting strict typing without reading the design doc. -->
    <aside :class="$style.softNotice">
      <strong>{{ t("wizard.schema.softTitle") }}</strong>
      <p>{{ t("wizard.schema.softBody") }}</p>
    </aside>

    <div :class="$style.summary">
      <span>
        <strong>{{ draft.entity_types.length }}</strong>
        {{ t("wizard.schema.entityTypesLabel") }}
      </span>
      <span>
        <strong>{{ draft.relation_types.length }}</strong>
        {{ t("wizard.schema.relationTypesLabel") }}
      </span>
      <span v-if="draft.proposed_by" :class="$style.muted">
        {{ t("wizard.schema.proposedBy") }} <code>{{ draft.proposed_by }}</code>
      </span>
    </div>

    <!-- Entity types -->
    <details :class="$style.section" open>
      <summary :class="$style.sectionHead">
        {{ t("wizard.schema.entityHead") }} ({{ draft.entity_types.length }})
      </summary>
      <div :class="$style.cards">
        <div
          v-for="(et, idx) in draft.entity_types"
          :key="idx"
          :class="$style.card"
        >
          <div :class="$style.row">
            <input
              :value="et.name"
              :class="$style.nameInput"
              @input="updateEntity(idx, { name: ($event.target as HTMLInputElement).value })"
            >
            <button
              type="button"
              :class="$style.removeBtn"
              :title="t('wizard.schema.remove')"
              @click="removeEntityType(idx)"
            >
              ×
            </button>
          </div>
          <textarea
            :value="et.description"
            :class="$style.descInput"
            :placeholder="t('wizard.schema.entityDescPlaceholder')"
            rows="2"
            @input="updateEntity(idx, { description: ($event.target as HTMLTextAreaElement).value })"
          />
          <input
            :value="examplesString(et.examples)"
            :class="$style.examplesInput"
            :placeholder="t('wizard.schema.examplesPlaceholder')"
            @input="updateEntity(idx, { examples: parseExamples(($event.target as HTMLInputElement).value) })"
          >
        </div>
        <button
          type="button"
          :class="$style.addBtn"
          @click="addEntityType"
        >
          + {{ t("wizard.schema.addEntity") }}
        </button>
      </div>
    </details>

    <!-- Relation types -->
    <details :class="$style.section" open>
      <summary :class="$style.sectionHead">
        {{ t("wizard.schema.relationHead") }} ({{ draft.relation_types.length }})
      </summary>
      <div :class="$style.cards">
        <div
          v-for="(rt, idx) in draft.relation_types"
          :key="idx"
          :class="$style.card"
        >
          <div :class="$style.row">
            <input
              :value="rt.name"
              :class="$style.nameInput"
              @input="updateRelation(idx, { name: ($event.target as HTMLInputElement).value })"
            >
            <label :class="$style.symmetricLabel">
              <input
                type="checkbox"
                :checked="rt.symmetric"
                @change="updateRelation(idx, { symmetric: ($event.target as HTMLInputElement).checked })"
              >
              {{ t("wizard.schema.symmetric") }}
            </label>
            <button
              type="button"
              :class="$style.removeBtn"
              :title="t('wizard.schema.remove')"
              @click="removeRelationType(idx)"
            >
              ×
            </button>
          </div>
          <textarea
            :value="rt.description"
            :class="$style.descInput"
            :placeholder="t('wizard.schema.relationDescPlaceholder')"
            rows="2"
            @input="updateRelation(idx, { description: ($event.target as HTMLTextAreaElement).value })"
          />
          <div :class="$style.dr">
            <div :class="$style.drCol">
              <span :class="$style.drLabel">{{ t("wizard.schema.domain") }}</span>
              <div :class="$style.chipRow">
                <button
                  v-for="name in entityNames"
                  :key="name"
                  type="button"
                  :class="[
                    $style.typeChip,
                    rt.domain.includes(name) ? $style.typeChip_on : '',
                  ]"
                  @click="updateRelation(idx, { domain: toggleInList(rt.domain, name) })"
                >
                  {{ name }}
                </button>
              </div>
            </div>
            <span :class="$style.arrow">{{ rt.symmetric ? "↔" : "→" }}</span>
            <div :class="$style.drCol">
              <span :class="$style.drLabel">{{ t("wizard.schema.range") }}</span>
              <div :class="$style.chipRow">
                <button
                  v-for="name in entityNames"
                  :key="name"
                  type="button"
                  :class="[
                    $style.typeChip,
                    rt.range.includes(name) ? $style.typeChip_on : '',
                  ]"
                  @click="updateRelation(idx, { range: toggleInList(rt.range, name) })"
                >
                  {{ name }}
                </button>
              </div>
            </div>
          </div>
          <input
            :value="examplesString(rt.examples)"
            :class="$style.examplesInput"
            :placeholder="t('wizard.schema.examplesPlaceholder')"
            @input="updateRelation(idx, { examples: parseExamples(($event.target as HTMLInputElement).value) })"
          >
        </div>
        <button
          type="button"
          :class="$style.addBtn"
          @click="addRelationType"
        >
          + {{ t("wizard.schema.addRelation") }}
        </button>
      </div>
    </details>

    <div :class="$style.actionBar">
      <button
        type="button"
        :class="$style.saveBtn"
        :disabled="saving || draft.entity_types.length === 0"
        @click="save"
      >
        {{ saving ? t("wizard.schema.saving") : t("wizard.schema.save") }}
      </button>
    </div>
  </section>
</template>

<style lang="scss" module>
  .step {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-md);
  }

  .title {
    margin: 0;
    font-size: 1.25rem;
    font-weight: 600;
  }

  .hint {
    margin: 0;
    color: var(--ksd-text-secondary-color);
  }

  .softNotice {
    border-left: 3px solid var(--gr-status-running, #f59e0b);
    background: rgba(245, 158, 11, 0.08);
    padding: var(--gr-space-sm) var(--gr-space-md);
    border-radius: var(--gr-radius-xs);
    font-size: 0.875rem;

    strong {
      display: block;
      margin-bottom: var(--gr-space-2xs);
      color: var(--gr-status-running, #b45309);
    }

    p {
      margin: 0;
      color: var(--ksd-text-main-color);
      line-height: 1.45;
    }
  }

  .proposeBar {
    display: flex;
    align-items: center;
    gap: var(--gr-space-sm);
    padding: var(--gr-space-sm);
    border: 1px solid var(--ksd-accent-color);
    border-radius: var(--gr-radius-sm);
    background: rgba(31, 119, 180, 0.06);
  }

  .sampleLabel {
    display: flex;
    align-items: center;
    gap: var(--gr-space-2xs);
    font-size: 0.875rem;
  }

  .numberInput {
    width: 4rem;
    padding: var(--gr-space-2xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-xs);
    background: var(--ksd-card-bg-color);
    color: var(--ksd-text-main-color);
  }

  .proposeBtn {
    padding: var(--gr-space-2xs) var(--gr-space-md);
    background: var(--ksd-accent-color);
    color: white;
    border: none;
    border-radius: var(--gr-radius-sm);
    cursor: pointer;
    font-weight: 500;

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }

  .skipBtn {
    margin-left: auto;
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    background: transparent;
    border: 1px solid var(--ksd-border-color);
    color: var(--ksd-text-secondary-color);
    border-radius: var(--gr-radius-sm);
    cursor: pointer;
  }

  .error {
    padding: var(--gr-space-sm);
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid var(--gr-status-failed);
    border-radius: var(--gr-radius-sm);
  }

  .summary {
    display: flex;
    gap: var(--gr-space-md);
    font-size: 0.875rem;
    color: var(--ksd-text-secondary-color);

    code {
      font-family: ui-monospace, monospace;
      background: var(--ksd-card-bg-color);
      padding: 0 var(--gr-space-2xs);
      border-radius: 3px;
    }
  }

  .muted {
    color: var(--ksd-text-secondary-color);
  }

  .section {
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    padding: var(--gr-space-sm);
  }

  .sectionHead {
    font-weight: 600;
    cursor: pointer;
    padding: var(--gr-space-2xs);
  }

  .cards {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-sm);
    margin-top: var(--gr-space-sm);
  }

  .card {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-xs);
    padding: var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-card-bg-color);
  }

  .row {
    display: flex;
    align-items: center;
    gap: var(--gr-space-sm);
  }

  .nameInput {
    flex: 1;
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-xs);
    background: transparent;
    color: var(--ksd-text-main-color);
    font-family: ui-monospace, monospace;
    font-weight: 600;
  }

  .descInput,
  .examplesInput {
    width: 100%;
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-xs);
    background: transparent;
    color: var(--ksd-text-main-color);
    font-family: inherit;
    font-size: 0.875rem;
    resize: vertical;
  }

  .symmetricLabel {
    display: flex;
    align-items: center;
    gap: var(--gr-space-2xs);
    font-size: 0.875rem;
    color: var(--ksd-text-secondary-color);
  }

  .removeBtn {
    width: 1.75rem;
    height: 1.75rem;
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-xs);
    background: transparent;
    color: var(--ksd-text-secondary-color);
    cursor: pointer;
    font-size: 1.25rem;
    line-height: 1;
  }

  .dr {
    display: flex;
    align-items: stretch;
    gap: var(--gr-space-sm);
  }

  .drCol {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
  }

  .drLabel {
    font-size: 0.75rem;
    text-transform: uppercase;
    color: var(--ksd-text-secondary-color);
    letter-spacing: 0.04em;
  }

  .chipRow {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gr-space-2xs);
  }

  .typeChip {
    padding: 2px var(--gr-space-2xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-xs);
    background: transparent;
    color: var(--ksd-text-secondary-color);
    font-size: 0.75rem;
    font-family: ui-monospace, monospace;
    cursor: pointer;
  }

  .typeChip_on {
    background: var(--ksd-accent-color);
    color: white;
    border-color: var(--ksd-accent-color);
  }

  .arrow {
    align-self: center;
    font-size: 1.25rem;
    color: var(--ksd-accent-color);
  }

  .addBtn {
    align-self: flex-start;
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    background: transparent;
    border: 1px dashed var(--ksd-border-color);
    color: var(--ksd-text-secondary-color);
    border-radius: var(--gr-radius-sm);
    cursor: pointer;
  }

  .actionBar {
    display: flex;
    justify-content: flex-end;
    gap: var(--gr-space-sm);
  }

  .saveBtn {
    padding: var(--gr-space-2xs) var(--gr-space-md);
    background: var(--gr-status-ready, #16a34a);
    color: white;
    border: none;
    border-radius: var(--gr-radius-sm);
    cursor: pointer;
    font-weight: 500;

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }
</style>
