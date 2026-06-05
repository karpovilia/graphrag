<script setup lang="ts">
  import { computed } from "vue";
  import { useI18n } from "vue-i18n";

  import type { Edge, Node } from "@/entities/api";

  type Props = {
    nodes: Node[];
    edges: Edge[];
  };
  const props = defineProps<Props>();
  const emit = defineEmits<{ (e: "close"): void }>();

  const { t } = useI18n();

  // Multi-select entity-type filter (lifted to the page → also filters the
  // canvas). [] = all types. Per-type colour override so types are
  // distinguishable on the canvas.
  const typeFilter = defineModel<string[]>("typeFilter", { default: () => [] });
  const typeColors = defineModel<Record<string, string>>("typeColors", {
    default: () => ({}),
  });

  // Only ENTITY-layer types — chunk / community / topic are layers, picked in
  // the toolbar above the graph, not here.
  const entityTypes = computed(() => {
    const counts = new Map<string, number>();
    for (const n of props.nodes) {
      if (n.layer !== "entity" || !n.type) continue;
      counts.set(n.type, (counts.get(n.type) ?? 0) + 1);
    }
    return [...counts.entries()]
      .map(([type, count]) => ({ type, count }))
      .sort((a, b) => b.count - a.count);
  });

  // A stable default colour per type (so the swatch shows something before the
  // user overrides it) — golden-angle hue spread.
  const PALETTE = [
    "#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
  ];
  function defaultColor(i: number): string {
    return PALETTE[i % PALETTE.length]!;
  }
  function colorOf(type: string, i: number): string {
    return typeColors.value[type] ?? defaultColor(i);
  }
  function setColor(type: string, color: string) {
    typeColors.value = { ...typeColors.value, [type]: color };
  }
  function toggleType(tp: string) {
    typeFilter.value = typeFilter.value.includes(tp)
      ? typeFilter.value.filter((x) => x !== tp)
      : [...typeFilter.value, tp];
  }
</script>

<template>
  <aside :class="$style.panel" :aria-label="t('layersPanel.aria')">
    <header :class="$style.header">
      <h2 :class="$style.title">{{ t("layersPanel.typesTitle") }}</h2>
      <button type="button" :class="$style.close" @click="emit('close')">×</button>
    </header>

    <p :class="$style.hint">{{ t("layersPanel.typesHint") }}</p>

    <ul :class="$style.list">
      <li v-for="(tt, i) in entityTypes" :key="tt.type" :class="$style.row">
        <input
          type="color"
          :value="colorOf(tt.type, i)"
          :class="$style.color"
          :title="t('layersPanel.colorTitle')"
          data-testid="type-color"
          @input="setColor(tt.type, ($event.target as HTMLInputElement).value)"
        />
        <button
          type="button"
          :class="[$style.chip, typeFilter.includes(tt.type) ? $style.chip_on : '']"
          data-testid="type-chip"
          @click="toggleType(tt.type)"
        >
          <span :class="$style.dot" :style="{ background: colorOf(tt.type, i) }" />
          {{ tt.type }}
          <span :class="$style.muted">{{ tt.count }}</span>
        </button>
      </li>
      <li v-if="!entityTypes.length" :class="$style.empty">
        {{ t("layersPanel.noTypes") }}
      </li>
    </ul>

    <button
      v-if="typeFilter.length"
      type="button"
      :class="$style.clear"
      @click="typeFilter = []"
    >
      {{ t("layersPanel.typeAll") }}
    </button>
  </aside>
</template>

<style lang="scss" module>
  .panel {
    position: absolute;
    top: var(--gr-space-md);
    right: var(--gr-space-md);
    width: 300px;
    max-height: calc(100vh - var(--gr-space-md) * 2);
    background: var(--ksd-card-bg-color);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-md);
    box-shadow: var(--gr-shadow-lg);
    display: flex;
    flex-direction: column;
    z-index: 100;
  }
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--gr-space-sm) var(--gr-space-md);
    border-bottom: 1px solid var(--ksd-border-color);
  }
  .title {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
  }
  .close {
    background: transparent;
    border: none;
    color: var(--ksd-text-secondary-color);
    cursor: pointer;
    font-size: 1.25rem;
    line-height: 1;
  }
  .hint {
    margin: 0;
    padding: var(--gr-space-sm) var(--gr-space-md) 0;
    font-size: 0.8rem;
    color: var(--ksd-text-secondary-color);
  }
  .list {
    list-style: none;
    margin: 0;
    padding: var(--gr-space-sm) var(--gr-space-md);
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
    overflow-y: auto;
  }
  .row {
    display: flex;
    align-items: center;
    gap: var(--gr-space-2xs);
  }
  .color {
    width: 22px;
    height: 22px;
    padding: 0;
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    cursor: pointer;
    flex-shrink: 0;
  }
  .chip {
    flex: 1;
    display: inline-flex;
    align-items: center;
    gap: var(--gr-space-2xs);
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    color: var(--ksd-text-main-color);
    font-size: 0.875rem;
    cursor: pointer;
    text-align: left;

    &:hover {
      border-color: var(--ksd-accent-color);
    }
  }
  .chip_on {
    background: var(--ksd-accent-color);
    color: #fff;

    .muted {
      color: rgb(255 255 255 / 80%);
    }
  }
  .dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .muted {
    margin-left: auto;
    color: var(--ksd-text-secondary-color);
    font-size: 0.8rem;
  }
  .empty {
    color: var(--ksd-text-secondary-color);
    font-size: 0.85rem;
  }
  .clear {
    margin: 0 var(--gr-space-md) var(--gr-space-md);
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border: 1px dashed var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    color: var(--ksd-text-secondary-color);
    font-size: 0.8rem;
    cursor: pointer;
  }
</style>
