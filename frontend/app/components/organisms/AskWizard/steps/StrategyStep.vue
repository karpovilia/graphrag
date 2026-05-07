<script setup lang="ts">
  import { useAsyncData } from "nuxt/app";

  import { useAskWizard } from "@/composables/use-ask-wizard";
  import { useApi } from "@/lib/api-client";

  const wizard = useAskWizard();
  const api = useApi();

  const { data: reasoners } = await useAsyncData("reasoners", () =>
    api.strategies.listKind("reasoner"),
  );
  const { data: aggregators } = await useAsyncData("aggregators", () =>
    api.strategies.listKind("aggregator"),
  );

  function selectReasoner(name: string) {
    wizard.data.value.reasoner = name;
    wizard.invalidateDownstream(2);
  }

  function selectAggregator(name: string) {
    wizard.data.value.aggregator = name;
    wizard.invalidateDownstream(2);
  }
</script>

<template>
  <section :class="$style.step">
    <h2 :class="$style.title">Стратегия</h2>
    <p :class="$style.hint">
      Reasoner работает с каждым вариантом независимо; aggregator
      используется только в режиме MoE — в Single ответ одного эксперта
      идёт напрямую.
    </p>

    <div :class="$style.section">
      <h3 :class="$style.subhead">Reasoner</h3>
      <ul :class="$style.cards">
        <li
          v-for="r in reasoners ?? []"
          :key="r.name"
          :class="[
            $style.card,
            wizard.data.value.reasoner === r.name ? $style.card_active : '',
          ]"
          @click="selectReasoner(r.name)"
        >
          <header :class="$style.cardHeader">
            <strong>{{ r.name }}</strong>
            <span :class="$style.costChip">{{ r.cost_hint ?? "?" }}</span>
          </header>
          <p :class="$style.summary">{{ r.summary }}</p>
        </li>
      </ul>
    </div>

    <div :class="$style.section" v-if="wizard.data.value.mode === 'moe'">
      <h3 :class="$style.subhead">Aggregator</h3>
      <ul :class="$style.cards">
        <li
          v-for="a in aggregators ?? []"
          :key="a.name"
          :class="[
            $style.card,
            wizard.data.value.aggregator === a.name ? $style.card_active : '',
          ]"
          @click="selectAggregator(a.name)"
        >
          <header :class="$style.cardHeader">
            <strong>{{ a.name }}</strong>
            <span :class="$style.costChip">{{ a.cost_hint ?? "?" }}</span>
          </header>
          <p :class="$style.summary">{{ a.summary }}</p>
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
    background: var(--ksd-bg-color);

    &:hover {
      border-color: var(--ksd-accent-color);
    }
  }

  .card_active {
    border-color: var(--ksd-accent-color);
    background: rgba(31, 119, 180, 0.08);
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
