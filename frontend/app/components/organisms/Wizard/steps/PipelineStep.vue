<script setup lang="ts">
  import { useAsyncData } from "nuxt/app";
  import { computed } from "vue";

  import { useBuildWizard } from "@/composables/use-build-wizard";
  import { useApi } from "@/lib/api-client";

  const wizard = useBuildWizard();
  const api = useApi();

  const { data: builders } = await useAsyncData("builders", () =>
    api.strategies.listKind("builder"),
  );
  const { data: cleaners } = await useAsyncData("cleaners", () =>
    api.strategies.listKind("cleaner"),
  );
  const { data: clusterers } = await useAsyncData("clusterers", () =>
    api.strategies.listKind("clusterer"),
  );

  const recommendation = computed(() => wizard.data.value.eda?.recommendation);

  function toggleCleaner(name: string) {
    const chain = wizard.data.value.build_request.cleaner_chain ?? [];
    const idx = chain.indexOf(name);
    const next = idx === -1 ? [...chain, name] : chain.filter((c) => c !== name);
    wizard.data.value.build_request.cleaner_chain = next;
    wizard.invalidateDownstream(3);
  }

  function selectBuilder(name: string) {
    wizard.data.value.build_request.builder = name;
    wizard.invalidateDownstream(3);
  }

  function selectClusterer(name: string | null) {
    wizard.data.value.build_request.clusterer = name;
    wizard.invalidateDownstream(3);
  }

  function isRecommended(kind: "builder" | "clusterer", name: string): boolean {
    if (!recommendation.value) return false;
    if (kind === "builder") return recommendation.value.builder === name;
    return recommendation.value.clusterer === name;
  }

  function isRecommendedCleaner(name: string): boolean {
    return recommendation.value?.cleaner_chain.includes(name) ?? false;
  }
</script>

<template>
  <section :class="$style.step">
    <h2 :class="$style.title">Пайплайн сборки</h2>
    <p :class="$style.hint">
      Выберите builder, cleaner-цепочку и clusterer. Зелёным помечены
      варианты, рекомендованные EDA-шагом.
    </p>

    <div :class="$style.section">
      <h3 :class="$style.subhead">Builder</h3>
      <ul :class="$style.cards">
        <li
          v-for="b in builders ?? []"
          :key="b.name"
          :class="[
            $style.card,
            wizard.data.value.build_request.builder === b.name ? $style.card_active : '',
            isRecommended('builder', b.name) ? $style.card_recommended : '',
          ]"
          @click="selectBuilder(b.name)"
        >
          <header :class="$style.cardHeader">
            <strong>{{ b.name }}</strong>
            <span :class="$style.costChip">{{ b.cost_hint ?? "?" }}</span>
          </header>
          <p :class="$style.summary">{{ b.summary }}</p>
        </li>
      </ul>
    </div>

    <div :class="$style.section">
      <h3 :class="$style.subhead">Cleaner-цепочка</h3>
      <p :class="$style.note">
        Порядок применения = порядок клика. Эти cleaner'ы запускаются друг
        за другом сразу после builder'а, до clusterer'а.
      </p>
      <div :class="$style.chain">
        <span
          v-for="(name, i) in wizard.data.value.build_request.cleaner_chain ?? []"
          :key="i"
          :class="$style.chainItem"
        >
          {{ i + 1 }}. {{ name }}
          <button
            type="button"
            :class="$style.chainRemove"
            @click="toggleCleaner(name)"
          >
            ×
          </button>
        </span>
        <span
          v-if="!(wizard.data.value.build_request.cleaner_chain ?? []).length"
          :class="$style.chainEmpty"
        >
          цепочка пустая (опционально)
        </span>
      </div>
      <ul :class="$style.cards">
        <li
          v-for="c in cleaners ?? []"
          :key="c.name"
          :class="[
            $style.card,
            (wizard.data.value.build_request.cleaner_chain ?? []).includes(c.name)
              ? $style.card_active
              : '',
            isRecommendedCleaner(c.name) ? $style.card_recommended : '',
          ]"
          @click="toggleCleaner(c.name)"
        >
          <header :class="$style.cardHeader">
            <strong>{{ c.name }}</strong>
            <span :class="$style.costChip">{{ c.cost_hint ?? "?" }}</span>
          </header>
          <p :class="$style.summary">{{ c.summary }}</p>
        </li>
      </ul>
    </div>

    <div :class="$style.section">
      <h3 :class="$style.subhead">Clusterer</h3>
      <ul :class="$style.cards">
        <li
          :class="[
            $style.card,
            wizard.data.value.build_request.clusterer === null ? $style.card_active : '',
          ]"
          @click="selectClusterer(null)"
        >
          <header :class="$style.cardHeader"><strong>(none)</strong></header>
          <p :class="$style.summary">Не запускать clusterer на этом сборе.</p>
        </li>
        <li
          v-for="cl in clusterers ?? []"
          :key="cl.name"
          :class="[
            $style.card,
            wizard.data.value.build_request.clusterer === cl.name ? $style.card_active : '',
            isRecommended('clusterer', cl.name) ? $style.card_recommended : '',
          ]"
          @click="selectClusterer(cl.name)"
        >
          <header :class="$style.cardHeader">
            <strong>{{ cl.name }}</strong>
            <span :class="$style.costChip">{{ cl.cost_hint ?? "?" }}</span>
          </header>
          <p :class="$style.summary">{{ cl.summary }}</p>
        </li>
      </ul>
    </div>
  </section>
</template>

<style lang="scss" module>
  .step {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-lg);
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

  .section {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-sm);
  }

  .subhead {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
  }

  .note {
    margin: 0;
    font-size: 0.875rem;
    color: var(--ksd-text-secondary-color);
  }

  .chain {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gr-space-2xs);
    align-items: center;
    padding: var(--gr-space-xs);
    border: 1px dashed var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
  }

  .chainItem {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    background: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
    border-radius: var(--gr-radius-sm);
    display: inline-flex;
    align-items: center;
    gap: var(--gr-space-2xs);
  }

  .chainRemove {
    background: transparent;
    border: none;
    color: var(--ksd-bg-color);
    cursor: pointer;
    font-weight: 700;
  }

  .chainEmpty {
    color: var(--ksd-text-secondary-color);
    font-size: 0.875rem;
  }

  .cards {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: var(--gr-space-sm);
  }

  .card {
    padding: var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    cursor: pointer;
    transition: all 0.15s ease;
    background: var(--ksd-bg-color);

    &:hover {
      border-color: var(--ksd-accent-color);
    }
  }

  .card_active {
    border-color: var(--ksd-accent-color);
    background: rgba(31, 119, 180, 0.08);
  }

  .card_recommended {
    box-shadow: 0 0 0 2px var(--gr-status-success);
  }

  .cardHeader {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--gr-space-2xs);
  }

  .costChip {
    font-size: 0.7rem;
    padding: 1px var(--gr-space-2xs);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-card-bg-color);
    color: var(--ksd-text-secondary-color);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .summary {
    margin: 0;
    font-size: 0.875rem;
    color: var(--ksd-text-secondary-color);
  }
</style>
