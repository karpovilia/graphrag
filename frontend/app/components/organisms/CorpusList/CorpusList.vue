<script setup lang="ts">
  import { useAsyncData } from "nuxt/app";
  import { computed } from "vue";
  import { useI18n } from "vue-i18n";

  import { useApi } from "@/lib/api-client";
  import { formatNumber, formatRelativeTime } from "@/lib/format";

  const { t } = useI18n();
  const api = useApi();

  const { data: corpora, refresh, error: corporaError } = await useAsyncData(
    "corpora",
    () => api.corpora.list(),
  );
  const { data: variants, error: variantsError } = await useAsyncData(
    "variants",
    () => api.graphs.list(),
  );

  const corporaWithVariants = computed(() => {
    const list = corpora.value ?? [];
    const allVariants = variants.value ?? [];
    return list.map((c) => ({
      corpus: c,
      variants: allVariants.filter((v) => v.corpus_id === c.id),
    }));
  });
</script>

<template>
  <div :class="$style.list">
    <header :class="$style.header">
      <div>
        <h1 :class="$style.title">{{ t("corpora.heading") }}</h1>
      </div>
      <NuxtLink to="/wizards/build" :class="$style.cta">
        {{ t("corpora.newCorpus") }}
      </NuxtLink>
    </header>

    <div v-if="corporaError || variantsError" :class="$style.error">
      {{ t("corpora.loadListFailed") }}:
      {{ corporaError?.message ?? variantsError?.message ?? "unknown error" }}
      <button :class="$style.retry" @click="() => refresh()">
        {{ t("common.submit") }}
      </button>
    </div>

    <div v-else-if="!corporaWithVariants.length" :class="$style.empty">
      <p>{{ t("corpora.empty") }}</p>
      <NuxtLink to="/wizards/build" :class="$style.ctaInline">
        {{ t("corpora.newCorpus") }}
      </NuxtLink>
    </div>

    <ul v-else :class="$style.cards">
      <li
        v-for="row in corporaWithVariants"
        :key="row.corpus.id"
        :class="$style.card"
      >
        <header :class="$style.cardHeader">
          <NuxtLink
            :to="`/corpora/${row.corpus.id}`"
            :class="$style.cardTitle"
          >
            {{ row.corpus.name }}
          </NuxtLink>
          <span :class="$style.muted">
            {{ formatRelativeTime(row.corpus.created_at) }}
          </span>
        </header>

        <p v-if="row.corpus.description" :class="$style.muted">
          {{ row.corpus.description }}
        </p>

        <dl :class="$style.metrics">
          <div>
            <dt>{{ t("corpora.documentsCount") }}</dt>
            <dd>{{ formatNumber(row.corpus.document_count) }}</dd>
          </div>
          <div>
            <dt>{{ t("corpora.variantsCount") }}</dt>
            <dd>{{ formatNumber(row.variants.length) }}</dd>
          </div>
          <div>
            <dt>{{ t("common.language") }}</dt>
            <dd>{{ row.corpus.language }}</dd>
          </div>
        </dl>

        <ul v-if="row.variants.length" :class="$style.variants">
          <li
            v-for="v in row.variants"
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
              {{ formatNumber(v.edge_count) }} {{ t("corpora.edgesShort") }}
            </span>
          </li>
        </ul>
      </li>
    </ul>
  </div>
</template>

<style lang="scss" module>
  .list {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-lg);
    padding: var(--gr-space-xl);
    overflow-y: auto;
    flex: 1;
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: var(--gr-space-lg);
  }

  .title {
    margin: 0 0 var(--gr-space-2xs);
    font-size: 1.75rem;
    font-weight: 700;
    color: var(--ksd-text-main-color);
  }

  .subtitle {
    margin: 0;
    max-width: 60ch;
    color: var(--ksd-text-secondary-color);
  }

  .cta {
    align-self: flex-start;
    padding: var(--gr-space-sm) var(--gr-space-md);
    background: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
    border-radius: var(--gr-radius-sm);
    font-weight: 600;
    text-decoration: none;
    box-shadow: var(--gr-shadow-sm);

    &:hover {
      filter: brightness(1.05);
      color: var(--ksd-bg-color);
    }
  }

  .ctaInline {
    color: var(--ksd-accent-color);
    font-weight: 600;
  }

  .error {
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid var(--gr-status-failed);
    border-radius: var(--gr-radius-md);
    padding: var(--gr-space-md);
    color: var(--ksd-text-main-color);
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

  .empty {
    padding: var(--gr-space-xl);
    text-align: center;
    color: var(--ksd-text-secondary-color);
    border: 1px dashed var(--ksd-border-color);
    border-radius: var(--gr-radius-md);
  }

  .cards {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
    gap: var(--gr-space-md);
  }

  .card {
    background: var(--ksd-card-bg-color);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-md);
    padding: var(--gr-space-md);
    box-shadow: var(--gr-shadow-sm);
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-sm);
    transition: box-shadow 0.15s ease, border-color 0.15s ease;
    position: relative;

    &:hover {
      box-shadow: var(--gr-shadow-md);
      border-color: var(--ksd-accent-color);
    }
  }

  .cardHeader {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: var(--gr-space-sm);
  }

  .cardTitle {
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--ksd-text-main-color);
    text-decoration: none;

    &:hover {
      color: var(--ksd-accent-color);
    }

    // Stretched-link: makes the whole .card a click target for the title
    // link without nesting <a> tags. Inner links (variants) lift above it
    // via z-index on .variant below.
    &::after {
      content: "";
      position: absolute;
      inset: 0;
      border-radius: inherit;
    }
  }

  .muted {
    color: var(--ksd-text-secondary-color);
    font-size: 0.875rem;
  }

  .metrics {
    display: flex;
    gap: var(--gr-space-md);
    margin: 0;

    dt {
      font-size: 0.75rem;
      color: var(--ksd-text-secondary-color);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    dd {
      margin: 0;
      font-size: 1.1rem;
      font-weight: 600;
      color: var(--ksd-text-main-color);
    }
  }

  .variants {
    list-style: none;
    margin: 0;
    padding: var(--gr-space-sm) 0 0;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
    border-top: 1px solid var(--ksd-border-color);
  }

  .variant {
    display: flex;
    align-items: center;
    gap: var(--gr-space-sm);
    padding-top: var(--gr-space-2xs);
    position: relative;
    z-index: 1;
  }

  .variantName {
    color: var(--ksd-text-main-color);
    font-weight: 500;
    text-decoration: none;

    &:hover {
      color: var(--ksd-accent-color);
    }
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
