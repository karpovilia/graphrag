<script setup lang="ts">
  import { computed, ref, watch } from "vue";

  import { useBuildWizard } from "@/composables/use-build-wizard";
  import { useApi } from "@/lib/api-client";
  import { formatNumber } from "@/lib/format";

  const wizard = useBuildWizard();
  const api = useApi();

  const loading = ref(false);
  const error = ref<string | null>(null);

  async function runEda() {
    error.value = null;
    loading.value = true;
    try {
      const docs = wizard.data.value.documents.filter((d) => d.text.trim());
      if (!docs.length) {
        error.value = "Нет документов с непустым текстом — вернитесь на шаг 2.";
        return;
      }
      const report = await api.eda.analyze({
        documents: docs.map((d) => ({ text: d.text })),
      });
      wizard.data.value.eda = report;
      // Pre-fill the pipeline from the recommendation; the user can
      // still override on step 4. Pre-filling here keeps the wizard
      // usable even if the user blasts through with default Next clicks.
      wizard.data.value.build_request = {
        ...wizard.data.value.build_request,
        builder: report.recommendation.builder,
        cleaner_chain: [...report.recommendation.cleaner_chain],
        clusterer: report.recommendation.clusterer,
      };
      wizard.invalidateDownstream(2);
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      loading.value = false;
    }
  }

  // Auto-run when this step is mounted and there's no report yet.
  watch(
    () => wizard.currentIndex.value,
    (idx) => {
      if (idx === 2 && !wizard.data.value.eda && !loading.value) {
        runEda();
      }
    },
    { immediate: true },
  );

  const report = computed(() => wizard.data.value.eda);
</script>

<template>
  <section :class="$style.step">
    <h2 :class="$style.title">EDA — рекомендации по корпусу</h2>
    <p :class="$style.hint">
      Быстрый анализ загруженного текста: длина документов, плотность сущностей,
      морфологический разброс. На основе этого подбираем дефолтные builder /
      cleaner / clusterer и стартовый набор типов узлов.
    </p>

    <div v-if="loading" :class="$style.loading">Анализирую корпус…</div>

    <div v-else-if="error" :class="$style.error">
      {{ error }}
      <button type="button" :class="$style.retry" @click="runEda">Повторить</button>
    </div>

    <div v-else-if="report" :class="$style.report">
      <div :class="$style.statsGrid">
        <div :class="$style.stat">
          <span :class="$style.statLabel">Документов</span>
          <span :class="$style.statValue">
            {{ formatNumber(report.document_stats.document_count) }}
          </span>
        </div>
        <div :class="$style.stat">
          <span :class="$style.statLabel">Символов всего</span>
          <span :class="$style.statValue">
            {{ formatNumber(report.document_stats.total_chars) }}
          </span>
        </div>
        <div :class="$style.stat">
          <span :class="$style.statLabel">Медиана длины</span>
          <span :class="$style.statValue">
            {{ formatNumber(Math.round(report.document_stats.median_chars)) }}
          </span>
        </div>
        <div :class="$style.stat">
          <span :class="$style.statLabel">NER-плотность / 1k</span>
          <span :class="$style.statValue">
            {{ report.entity_density_per_1k_chars.toFixed(2) }}
          </span>
        </div>
        <div :class="$style.stat">
          <span :class="$style.statLabel">Морф. разброс</span>
          <span :class="$style.statValue">
            {{ report.morphological_dispersion.toFixed(2) }}
          </span>
        </div>
      </div>

      <div :class="$style.recommendation">
        <h3 :class="$style.subhead">Рекомендация</h3>
        <p :class="$style.rationale">{{ report.recommendation.rationale }}</p>

        <div :class="$style.recRow">
          <strong>Builder:</strong>
          <code>{{ report.recommendation.builder }}</code>
        </div>
        <div :class="$style.recRow">
          <strong>Cleaner-цепочка:</strong>
          <code>{{ report.recommendation.cleaner_chain.join(" → ") || "—" }}</code>
        </div>
        <div :class="$style.recRow">
          <strong>Clusterer:</strong>
          <code>{{ report.recommendation.clusterer }}</code>
        </div>
      </div>

      <div v-if="report.recommendation.node_types.length" :class="$style.types">
        <h3 :class="$style.subhead">Типы узлов</h3>
        <ul :class="$style.typeList">
          <li
            v-for="t in report.recommendation.node_types"
            :key="t.name"
            :class="$style.typeChip"
            :style="{ borderColor: t.suggested_color || 'var(--ksd-border-color)' }"
          >
            <strong>{{ t.label }}</strong>
            <span :class="$style.typeMuted">
              {{ t.name }} · {{ t.evidence_count }} упоминаний
            </span>
          </li>
        </ul>
      </div>

      <button type="button" :class="$style.rerun" @click="runEda">
        Перезапустить анализ
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

  .loading {
    padding: var(--gr-space-md);
    color: var(--ksd-text-secondary-color);
  }

  .error {
    padding: var(--gr-space-md);
    border: 1px solid var(--gr-status-failed);
    background: rgba(239, 68, 68, 0.08);
    border-radius: var(--gr-radius-sm);
  }

  .retry {
    margin-left: var(--gr-space-md);
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    background: transparent;
    border: 1px solid var(--ksd-accent-color);
    color: var(--ksd-accent-color);
    border-radius: var(--gr-radius-sm);
    cursor: pointer;
  }

  .report {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-md);
  }

  .statsGrid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: var(--gr-space-sm);
  }

  .stat {
    padding: var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
  }

  .statLabel {
    font-size: 0.75rem;
    color: var(--ksd-text-secondary-color);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .statValue {
    font-size: 1.25rem;
    font-weight: 600;
  }

  .subhead {
    margin: 0 0 var(--gr-space-xs);
    font-size: 1rem;
    font-weight: 600;
  }

  .recommendation {
    padding: var(--gr-space-md);
    border: 1px solid var(--ksd-accent-color);
    border-radius: var(--gr-radius-sm);
    background: rgba(31, 119, 180, 0.05);
  }

  .rationale {
    white-space: pre-line;
    margin: 0 0 var(--gr-space-sm);
  }

  .recRow {
    display: flex;
    align-items: baseline;
    gap: var(--gr-space-sm);
    margin-bottom: var(--gr-space-2xs);

    code {
      font-family: ui-monospace, monospace;
      background: var(--ksd-card-bg-color);
      padding: 0 var(--gr-space-2xs);
      border-radius: 3px;
    }
  }

  .types {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-xs);
  }

  .typeList {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: var(--gr-space-2xs);
  }

  .typeChip {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border: 2px solid;
    border-radius: var(--gr-radius-sm);
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .typeMuted {
    font-size: 0.75rem;
    color: var(--ksd-text-secondary-color);
  }

  .rerun {
    align-self: flex-start;
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    background: transparent;
    border: 1px solid var(--ksd-border-color);
    color: var(--ksd-text-main-color);
    border-radius: var(--gr-radius-sm);
    cursor: pointer;
  }
</style>
