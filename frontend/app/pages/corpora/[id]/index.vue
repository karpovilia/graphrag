<script setup lang="ts">
  import { useAsyncData } from "nuxt/app";
  import { useRoute } from "vue-router";
  import { useI18n } from "vue-i18n";

  import { useApi } from "@/lib/api-client";
  import { formatNumber, formatRelativeTime } from "@/lib/format";

  const { t } = useI18n();
  const route = useRoute();
  const corpusId = String(route.params.id);
  const api = useApi();

  const { data: corpus, error: corpusError } = await useAsyncData(
    `corpus:${corpusId}`,
    () => api.corpora.get(corpusId),
  );
  const { data: documents, error: documentsError } = await useAsyncData(
    `corpus-documents:${corpusId}`,
    () => api.corpora.listDocuments(corpusId),
  );
  const { data: variants, error: variantsError } = await useAsyncData(
    `corpus-variants:${corpusId}`,
    () => api.graphs.list(corpusId),
  );

  const error = corpusError.value || documentsError.value || variantsError.value;
</script>

<template>
  <div :class="$style.page">
    <header :class="$style.header">
      <NuxtLink to="/corpora" :class="$style.back">{{ t("corpora.backToList") }}</NuxtLink>
      <h1 v-if="corpus" :class="$style.title">{{ corpus.name }}</h1>
      <p v-if="corpus?.description" :class="$style.subtitle">
        {{ corpus.description }}
      </p>
    </header>

    <div v-if="error" :class="$style.error">
      {{ t("corpora.loadFailed") }}: {{ error.message }}
    </div>

    <div v-else-if="corpus" :class="$style.body">
      <dl :class="$style.metrics">
        <div>
          <dt>{{ t("corpora.documentsCount") }}</dt>
          <dd>{{ formatNumber(corpus.document_count) }}</dd>
        </div>
        <div>
          <dt>{{ t("corpora.variantsCount") }}</dt>
          <dd>{{ formatNumber((variants ?? []).length) }}</dd>
        </div>
        <div>
          <dt>{{ t("common.language") }}</dt>
          <dd>{{ corpus.language }}</dd>
        </div>
        <div>
          <dt>{{ t("corpora.createdAt") }}</dt>
          <dd>{{ formatRelativeTime(corpus.created_at) }}</dd>
        </div>
      </dl>

      <section :class="$style.section">
        <h2 :class="$style.subhead">
          {{ t("corpora.variantsHeading") }}
          <span :class="$style.muted">({{ (variants ?? []).length }})</span>
          <NuxtLink
            :to="`/wizards/build?corpus_id=${corpusId}&step=4`"
            :class="$style.cta"
          >
            {{ t("corpora.newVariant") }}
          </NuxtLink>
        </h2>
        <ul v-if="(variants ?? []).length" :class="$style.variants">
          <li
            v-for="v in variants ?? []"
            :key="v.id"
            :class="$style.variant"
          >
            <NuxtLink :to="`/graphs/${v.id}`" :class="$style.variantName">
              {{ v.name }}
            </NuxtLink>
            <span :class="[$style.chip, $style[`chip_${v.status}`] || '']">
              {{ v.status }}
            </span>
            <span :class="$style.muted">
              {{ v.builder }} · {{ formatNumber(v.node_count) }}
              {{ t("corpora.nodesShort") }} ·
              {{ formatNumber(v.edge_count) }}
              {{ t("corpora.edgesShort") }} · v{{ v.version }}
            </span>
          </li>
        </ul>
        <p v-else :class="$style.muted">{{ t("corpora.noVariants") }}</p>
      </section>

      <section :class="$style.section">
        <h2 :class="$style.subhead">
          {{ t("corpora.documentsHeading") }}
          <span :class="$style.muted">({{ (documents ?? []).length }})</span>
        </h2>
        <ul v-if="(documents ?? []).length" :class="$style.documents">
          <li
            v-for="d in documents ?? []"
            :key="d.id"
            :class="$style.documentRow"
          >
            <NuxtLink
              :to="`/corpora/${corpusId}/documents/${d.id}`"
              :class="$style.docTitle"
            >
              {{ d.title }}
            </NuxtLink>
            <span :class="$style.muted">
              {{ formatNumber(d.char_length) }} · {{ d.language }}
            </span>
          </li>
        </ul>
        <p v-else :class="$style.muted">{{ t("corpora.noDocuments") }}</p>
      </section>
    </div>
  </div>
</template>

<style lang="scss" module>
  .page {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-lg);
    padding: var(--gr-space-xl);
    overflow-y: auto;
    flex: 1;
  }

  .header {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
  }

  .back {
    font-size: 0.875rem;
    color: var(--ksd-text-secondary-color);
    text-decoration: none;
    width: fit-content;

    &:hover {
      color: var(--ksd-accent-color);
    }
  }

  .title {
    margin: 0;
    font-size: 1.75rem;
    font-weight: 700;
    color: var(--ksd-text-main-color);
  }

  .subtitle {
    margin: 0;
    color: var(--ksd-text-secondary-color);
  }

  .error {
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid var(--gr-status-failed);
    border-radius: var(--gr-radius-md);
    padding: var(--gr-space-md);
    color: var(--ksd-text-main-color);
  }

  .body {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-lg);
  }

  .metrics {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gr-space-lg);
    margin: 0;
    padding: var(--gr-space-md);
    background: var(--ksd-card-bg-color);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-md);

    dt {
      font-size: 0.7rem;
      color: var(--ksd-text-secondary-color);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    dd {
      margin: 0;
      font-size: 1.25rem;
      font-weight: 600;
      color: var(--ksd-text-main-color);
    }
  }

  .section {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-sm);
  }

  .subhead {
    margin: 0;
    font-size: 1.1rem;
    font-weight: 600;
    display: flex;
    align-items: baseline;
    gap: var(--gr-space-xs);
  }

  .cta {
    margin-left: auto;
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    font-size: 0.875rem;
    font-weight: 500;
    color: var(--ksd-accent-color);
    border: 1px solid var(--ksd-accent-color);
    border-radius: var(--gr-radius-sm);
    text-decoration: none;

    &:hover {
      background: var(--ksd-accent-color);
      color: white;
    }
  }

  .muted {
    color: var(--ksd-text-secondary-color);
    font-size: 0.875rem;
    font-weight: 400;
  }

  .variants,
  .documents {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
  }

  .variant,
  .documentRow {
    display: flex;
    align-items: center;
    gap: var(--gr-space-sm);
    padding: var(--gr-space-xs) var(--gr-space-sm);
    background: var(--ksd-card-bg-color);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
  }

  .variantName,
  .docTitle {
    color: var(--ksd-text-main-color);
    font-weight: 500;
    text-decoration: none;
  }

  .variantName:hover,
  .docTitle:hover {
    color: var(--ksd-accent-color);
  }

  .chip {
    padding: 2px var(--gr-space-xs);
    font-size: 0.75rem;
    border-radius: var(--gr-radius-sm);
    background: var(--gr-status-pending);
    color: white;
    text-transform: lowercase;
  }

  .chip_ready {
    background: var(--gr-status-success);
  }

  .chip_running,
  .chip_building {
    background: var(--gr-status-running);
  }

  .chip_failed {
    background: var(--gr-status-failed);
  }

  .chip_archived {
    background: var(--gr-status-pending);
  }
</style>
