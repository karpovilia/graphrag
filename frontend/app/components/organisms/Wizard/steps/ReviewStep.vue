<script setup lang="ts">
  import { computed, ref } from "vue";
  import { navigateTo } from "nuxt/app";

  import { useBuildWizard } from "@/composables/use-build-wizard";
  import { useApi } from "@/lib/api-client";

  const wizard = useBuildWizard();
  const api = useApi();

  const building = ref(false);
  const error = ref<string | null>(null);
  const stage = ref<string>("");

  const summary = computed(() => ({
    name: wizard.data.value.corpus_name || "(без названия)",
    documents: wizard.data.value.documents.filter((d) => d.text.trim()).length,
    builder: wizard.data.value.build_request.builder,
    cleaners: wizard.data.value.build_request.cleaner_chain ?? [],
    clusterer: wizard.data.value.build_request.clusterer ?? "(none)",
  }));

  async function build() {
    error.value = null;
    building.value = true;
    try {
      stage.value = "Создаю корпус…";
      const corpus = await api.corpora.create({
        name: wizard.data.value.corpus_name || "untitled corpus",
        description: wizard.data.value.corpus_description || null,
        language: wizard.data.value.language || "ru",
      });
      wizard.data.value.corpus_id = corpus.id;

      stage.value = "Загружаю документы…";
      const docs = wizard.data.value.documents.filter((d) => d.text.trim());
      for (const d of docs) {
        await api.corpora.createDocument(corpus.id, {
          title: d.title || "untitled",
          text: d.text,
          language: wizard.data.value.language,
        });
      }

      stage.value = "Запускаю сборку графа…";
      const variant = await api.corpora.buildVariant(corpus.id, {
        ...wizard.data.value.build_request,
        name: wizard.data.value.build_request.name || "v1",
      });

      wizard.markCompleted(4);
      stage.value = "Готово!";
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
    <h2 :class="$style.title">Подтверждение запуска</h2>
    <p :class="$style.hint">
      Проверьте параметры. Если всё ок, нажмите «Запустить сборку» — корпус
      и документы попадут в БД, builder/cleaner/clusterer выполнятся
      синхронно, и вы окажетесь на странице нового варианта графа.
    </p>

    <dl :class="$style.summary">
      <div :class="$style.row">
        <dt>Корпус</dt>
        <dd>{{ summary.name }}</dd>
      </div>
      <div :class="$style.row">
        <dt>Документов</dt>
        <dd>{{ summary.documents }}</dd>
      </div>
      <div :class="$style.row">
        <dt>Builder</dt>
        <dd><code>{{ summary.builder }}</code></dd>
      </div>
      <div :class="$style.row">
        <dt>Cleaner-цепочка</dt>
        <dd><code>{{ summary.cleaners.join(" → ") || "—" }}</code></dd>
      </div>
      <div :class="$style.row">
        <dt>Clusterer</dt>
        <dd><code>{{ summary.clusterer }}</code></dd>
      </div>
    </dl>

    <div v-if="building" :class="$style.progress">
      <span :class="$style.spinner"></span>
      {{ stage }}
    </div>

    <div v-else-if="error" :class="$style.error">
      Ошибка сборки: {{ error }}
    </div>

    <button
      v-else
      type="button"
      :class="$style.cta"
      :disabled="!summary.documents"
      @click="build"
    >
      Запустить сборку
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
