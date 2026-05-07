<script setup lang="ts">
  import { useAsyncData } from "nuxt/app";
  import { computed } from "vue";

  import { useAskWizard } from "@/composables/use-ask-wizard";
  import { useApi } from "@/lib/api-client";
  import { formatNumber } from "@/lib/format";

  const wizard = useAskWizard();
  const api = useApi();

  const { data: variants } = await useAsyncData("variants-for-ask", () =>
    api.graphs.list(),
  );

  const requiredCount = computed(() =>
    wizard.data.value.mode === "single" ? 1 : 2,
  );

  function toggle(id: string) {
    const ids = wizard.data.value.variant_ids;
    const idx = ids.indexOf(id);
    if (idx === -1) {
      // Single mode: replace; MoE: append.
      wizard.data.value.variant_ids =
        wizard.data.value.mode === "single" ? [id] : [...ids, id];
    } else {
      wizard.data.value.variant_ids = ids.filter((v) => v !== id);
    }
    wizard.invalidateDownstream(1);
  }
</script>

<template>
  <section :class="$style.step">
    <h2 :class="$style.title">Варианты графа</h2>
    <p :class="$style.hint">
      Режим: <strong>{{ wizard.data.value.mode }}</strong> ·
      нужно выбрать минимум {{ requiredCount }}, выбрано
      <strong>{{ wizard.data.value.variant_ids.length }}</strong>.
    </p>

    <ul :class="$style.list" v-if="(variants ?? []).length">
      <li
        v-for="v in variants ?? []"
        :key="v.id"
        :class="[
          $style.row,
          wizard.data.value.variant_ids.includes(v.id) ? $style.row_active : '',
        ]"
        @click="toggle(v.id)"
      >
        <input
          type="checkbox"
          :checked="wizard.data.value.variant_ids.includes(v.id)"
          @click.stop
          @change="toggle(v.id)"
        />
        <div :class="$style.body">
          <strong>{{ v.name }}</strong>
          <span :class="$style.muted">
            {{ v.builder }} · {{ formatNumber(v.node_count) }} узлов ·
            {{ formatNumber(v.edge_count) }} рёбер · v{{ v.version }}
          </span>
        </div>
        <span :class="[$style.chip, $style[`chip_${v.status}`] || '']">
          {{ v.status }}
        </span>
      </li>
    </ul>
    <p v-else :class="$style.empty">
      Нет ни одного варианта графа — соберите хотя бы один в
      <NuxtLink to="/wizards/build">визарде сборки</NuxtLink>.
    </p>
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

  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
  }

  .row {
    display: flex;
    align-items: center;
    gap: var(--gr-space-sm);
    padding: var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    cursor: pointer;
    background: var(--ksd-bg-color);
  }

  .row_active {
    border-color: var(--ksd-accent-color);
    background: rgba(31, 119, 180, 0.08);
  }

  .body {
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
  }

  .muted {
    color: var(--ksd-text-secondary-color);
    font-size: 0.875rem;
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

  .empty {
    padding: var(--gr-space-md);
    text-align: center;
    color: var(--ksd-text-secondary-color);
  }
</style>
