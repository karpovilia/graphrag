<script setup lang="ts">
  import { useAsyncData } from "nuxt/app";
  import { useRoute } from "vue-router";
  import { useI18n } from "vue-i18n";

  import { useApi } from "@/lib/api-client";
  import { formatNumber, formatRelativeTime } from "@/lib/format";

  const { t } = useI18n();
  const route = useRoute();
  const corpusId = String(route.params.id);
  const documentId = String(route.params.docId);
  const api = useApi();

  const { data: document, error } = await useAsyncData(
    `document:${corpusId}:${documentId}`,
    () => api.corpora.getDocument(corpusId, documentId),
  );
</script>

<template>
  <div :class="$style.page">
    <header :class="$style.header">
      <NuxtLink :to="`/corpora/${corpusId}`" :class="$style.back">
        {{ t("corpora.backToCorpus") }}
      </NuxtLink>
      <h1 v-if="document" :class="$style.title">{{ document.title }}</h1>
    </header>

    <div v-if="error" :class="$style.error">
      {{ t("corpora.documentLoadFailed") }}: {{ error.message }}
    </div>

    <div v-else-if="document" :class="$style.body">
      <dl :class="$style.metrics">
        <div>
          <dt>{{ t("corpora.documentsCount") }}</dt>
          <dd>{{ formatNumber(document.char_length) }}</dd>
        </div>
        <div>
          <dt>{{ t("common.language") }}</dt>
          <dd>{{ document.language }}</dd>
        </div>
        <div>
          <dt>{{ t("corpora.createdAt") }}</dt>
          <dd>{{ formatRelativeTime(document.created_at) }}</dd>
        </div>
        <div v-if="document.source_uri">
          <dt>{{ t("corpora.documentSource") }}</dt>
          <dd>
            <a :href="document.source_uri" target="_blank" rel="noopener">
              {{ document.source_uri }}
            </a>
          </dd>
        </div>
        <div :class="$style.metricWide">
          <dt>{{ t("corpora.documentSha") }}</dt>
          <dd :class="$style.mono">{{ document.sha256 }}</dd>
        </div>
      </dl>

      <section :class="$style.section">
        <h2 :class="$style.subhead">{{ t("corpora.documentText") }}</h2>
        <pre v-if="document.text" :class="$style.text">{{ document.text }}</pre>
        <p v-else :class="$style.muted">{{ t("corpora.documentEmpty") }}</p>
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
      font-size: 1rem;
      font-weight: 500;
      color: var(--ksd-text-main-color);
      word-break: break-all;
    }
  }

  .metricWide {
    flex-basis: 100%;
  }

  .mono {
    font-family: var(--gr-font-mono, ui-monospace, SFMono-Regular, monospace);
    font-size: 0.85rem;
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
  }

  .text {
    margin: 0;
    padding: var(--gr-space-md);
    background: var(--ksd-card-bg-color);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-md);
    color: var(--ksd-text-main-color);
    white-space: pre-wrap;
    word-wrap: break-word;
    font-family: var(--gr-font-mono, ui-monospace, SFMono-Regular, monospace);
    font-size: 0.9rem;
    line-height: 1.55;
    max-height: 70vh;
    overflow: auto;
  }

  .muted {
    color: var(--ksd-text-secondary-color);
    font-size: 0.875rem;
    font-weight: 400;
  }
</style>
