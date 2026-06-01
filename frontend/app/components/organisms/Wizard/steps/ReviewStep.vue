<script setup lang="ts">
  import { computed, ref } from "vue";
  import { navigateTo } from "nuxt/app";
  import { useI18n } from "vue-i18n";

  import { useBuildWizard } from "@/composables/use-build-wizard";
  import { useApi } from "@/lib/api-client";

  const { t } = useI18n();
  const wizard = useBuildWizard();
  const api = useApi();

  const building = ref(false);
  const error = ref<string | null>(null);
  const stage = ref<string>("");

  const summary = computed(() => ({
    name: wizard.data.value.corpus_name || t("wizard.review.untitled"),
    documents: wizard.data.value.documents.filter((d) => d.text.trim()).length,
    builder: wizard.data.value.build_request.builder,
    cleaners: wizard.data.value.build_request.cleaner_chain ?? [],
    clusterer: wizard.data.value.build_request.clusterer ?? "(none)",
    addingToExisting: Boolean(wizard.data.value.corpus_id),
  }));

  async function build() {
    error.value = null;
    building.value = true;
    try {
      // Adding a variant to an existing corpus (deep-link from
      // /corpora/{id}): skip create + document upload, the corpus is
      // already there.
      let corpusId = wizard.data.value.corpus_id;
      if (!corpusId) {
        stage.value = t("wizard.review.creatingCorpus");
        const corpus = await api.corpora.create({
          name: wizard.data.value.corpus_name || "untitled corpus",
          description: wizard.data.value.corpus_description || null,
          language: wizard.data.value.language || "ru",
        });
        corpusId = corpus.id;
        wizard.data.value.corpus_id = corpusId;

        stage.value = t("wizard.review.uploadingDocs");
        const docs = wizard.data.value.documents.filter((d) => d.text.trim());
        for (const d of docs) {
          await api.corpora.createDocument(corpusId, {
            title: d.title || "untitled",
            text: d.text,
            language: wizard.data.value.language,
          });
        }
      }

      stage.value = t("wizard.review.buildingGraph");
      const variant = await api.corpora.buildVariant(corpusId, {
        ...wizard.data.value.build_request,
        name: wizard.data.value.build_request.name || "v1",
      });

      wizard.markCompleted(4);
      stage.value = t("wizard.review.ready");
      await navigateTo(`/graphs/${variant.id}`);
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      building.value = false;
    }
  }

  defineExpose({ build, building });
</script>

<template>
  <section :class="$style.step">
    <h2 :class="$style.title">{{ t("wizard.review.title") }}</h2>
    <p :class="$style.hint">{{ t("wizard.review.hint") }}</p>

    <dl :class="$style.summary">
      <div :class="$style.row">
        <dt>{{ t("wizard.review.fieldCorpus") }}</dt>
        <dd>{{ summary.name }}</dd>
      </div>
      <div :class="$style.row">
        <dt>{{ t("wizard.review.fieldDocuments") }}</dt>
        <dd>{{ summary.documents }}</dd>
      </div>
      <div :class="$style.row">
        <dt>{{ t("wizard.review.fieldBuilder") }}</dt>
        <dd><code>{{ summary.builder }}</code></dd>
      </div>
      <div :class="$style.row">
        <dt>{{ t("wizard.review.fieldCleaners") }}</dt>
        <dd><code>{{ summary.cleaners.join(" → ") || "—" }}</code></dd>
      </div>
      <div :class="$style.row">
        <dt>{{ t("wizard.review.fieldClusterer") }}</dt>
        <dd><code>{{ summary.clusterer }}</code></dd>
      </div>
      <div :class="$style.row">
        <dt>{{ t("common.language") }}</dt>
        <dd><code>{{ wizard.data.value.build_request.output_language ?? "ru" }}</code></dd>
      </div>
    </dl>

    <div v-if="building" :class="$style.progress">
      <span :class="$style.spinner"></span>
      {{ stage }}
    </div>

    <div v-else-if="error" :class="$style.error">
      {{ t("wizard.review.errorBuilding") }}: {{ error }}
    </div>

    <button
      v-else
      type="button"
      :class="$style.cta"
      :disabled="!summary.addingToExisting && !summary.documents"
      @click="build"
    >
      {{ t("wizard.review.submit") }}
    </button>
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

  .summary {
    margin: 0;
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: var(--gr-space-2xs) var(--gr-space-md);
  }

  .row {
    display: contents;

    dt {
      font-weight: 500;
      color: var(--ksd-text-secondary-color);
    }

    dd {
      margin: 0;

      code {
        font-family: ui-monospace, monospace;
        background: var(--ksd-card-bg-color);
        padding: 0 var(--gr-space-2xs);
        border-radius: 3px;
      }
    }
  }

  .progress {
    display: flex;
    align-items: center;
    gap: var(--gr-space-sm);
    padding: var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
  }

  .spinner {
    width: 16px;
    height: 16px;
    border: 2px solid var(--ksd-border-color);
    border-top-color: var(--ksd-accent-color);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  .error {
    padding: var(--gr-space-sm);
    border: 1px solid var(--gr-status-failed);
    background: rgba(239, 68, 68, 0.08);
    border-radius: var(--gr-radius-sm);
    color: var(--ksd-text-main-color);
  }

  .cta {
    align-self: flex-start;
    padding: var(--gr-space-sm) var(--gr-space-xl);
    background: var(--gr-status-success);
    color: white;
    border: none;
    border-radius: var(--gr-radius-sm);
    font-weight: 600;
    cursor: pointer;

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    &:hover:not(:disabled) {
      filter: brightness(1.05);
    }
  }
</style>
