<script setup lang="ts">
  // Layer Map overlay (Phase 6.6.2). Toggled by hotkey `L` from
  // LayeredGraph. Lets the user reorder layers visually (drag handles)
  // and tune per-layer opacity. Drag-reorder changes ONLY the visual
  // Z-stacking — semantic ordering chunk → entity → community → topic
  // stays fixed in the data model (memory: project_redesign_r2.md item 8).

  import { computed, ref } from "vue";

  import type { Layer } from "@/entities/api";

  import { LAYER_COLORS, LAYER_ORDER } from "./lib/alpha";

  type Props = {
    activeLayer: Layer | null;
    visualOrder: Layer[];
    perLayerAlpha: Partial<Record<Layer, number>>;
    sliceMode: boolean;
  };

  const props = defineProps<Props>();
  const emit = defineEmits<{
    (e: "close"): void;
    (e: "update:activeLayer", value: Layer | null): void;
    (e: "update:visualOrder", value: Layer[]): void;
    (e: "update:perLayerAlpha", value: Partial<Record<Layer, number>>): void;
    (e: "update:sliceMode", value: boolean): void;
    (e: "reset"): void;
  }>();

  const dragIndex = ref<number | null>(null);

  function onDragStart(i: number) {
    dragIndex.value = i;
  }

  function onDragOver(e: DragEvent, i: number) {
    e.preventDefault();
    if (dragIndex.value === null || dragIndex.value === i) return;
    const next = [...props.visualOrder];
    const [moved] = next.splice(dragIndex.value, 1);
    if (!moved) return;
    next.splice(i, 0, moved);
    dragIndex.value = i;
    emit("update:visualOrder", next);
  }

  function onDragEnd() {
    dragIndex.value = null;
  }

  function setAlpha(layer: Layer, value: number) {
    emit("update:perLayerAlpha", { ...props.perLayerAlpha, [layer]: value });
  }

  function alphaFor(layer: Layer): number {
    const v = props.perLayerAlpha[layer];
    return v == null ? 1 : v;
  }

  const knownLayers = computed(() => {
    // Surface every Layer enum value, but draw them in the user's
    // visual order. Anything missing from visualOrder gets appended.
    const seen = new Set(props.visualOrder);
    const tail = LAYER_ORDER.filter((l) => !seen.has(l));
    return [...props.visualOrder, ...tail];
  });
</script>

<template>
  <div :class="$style.overlay" @click.self="emit('close')">
    <aside :class="$style.panel" aria-label="Layer Map">
      <header :class="$style.header">
        <h2 :class="$style.title">Layer Map</h2>
        <button type="button" :class="$style.close" @click="emit('close')">
          ×
        </button>
      </header>

      <p :class="$style.hint">
        Перетащите за <code>⋮⋮</code> чтобы изменить визуальный Z-stacking.
        Семантическая иерархия chunk → entity → community → topic не
        меняется — это только порядок отрисовки.
      </p>

      <ul :class="$style.list">
        <li
          v-for="(layer, i) in knownLayers"
          :key="layer"
          :class="[
            $style.row,
            activeLayer === layer ? $style.row_active : '',
            dragIndex === i ? $style.row_dragging : '',
          ]"
          draggable="true"
          @dragstart="onDragStart(i)"
          @dragover="onDragOver($event, i)"
          @dragend="onDragEnd"
        >
          <span :class="$style.handle" title="перетащить">⋮⋮</span>
          <span :class="$style.swatch" :style="{ background: LAYER_COLORS[layer] }" />
          <strong :class="$style.layerName">{{ layer }}</strong>

          <div :class="$style.controls">
            <label :class="$style.opacity">
              <span :class="$style.muted">α {{ alphaFor(layer).toFixed(2) }}</span>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                :value="alphaFor(layer)"
                @input="(e) => setAlpha(layer, Number((e.target as HTMLInputElement).value))"
              />
            </label>

            <button
              type="button"
              :class="[
                $style.focus,
                activeLayer === layer ? $style.focus_active : '',
              ]"
              :title="`hotkey ${LAYER_ORDER.indexOf(layer) + 1}`"
              @click="emit('update:activeLayer', activeLayer === layer ? null : layer)"
            >
              {{ activeLayer === layer ? "focused" : "focus" }}
            </button>
          </div>
        </li>
      </ul>

      <footer :class="$style.footer">
        <label :class="$style.slice">
          <input
            type="checkbox"
            :checked="sliceMode"
            @change="(e) => emit('update:sliceMode', (e.target as HTMLInputElement).checked)"
          />
          Slice — скрыть всё кроме активного слоя
        </label>
        <button type="button" :class="$style.resetBtn" @click="emit('reset')">
          Сбросить
        </button>
      </footer>
    </aside>
  </div>
</template>

<style lang="scss" module>
  .overlay {
    position: absolute;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 100;
  }

  .panel {
    width: min(540px, 90%);
    max-height: 80vh;
    background: var(--ksd-card-bg-color);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-md);
    box-shadow: var(--gr-shadow-lg);
    padding: var(--gr-space-md);
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-sm);
    overflow: hidden;
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }

  .title {
    margin: 0;
    font-size: 1.1rem;
    font-weight: 600;
  }

  .close {
    background: transparent;
    border: none;
    color: var(--ksd-text-secondary-color);
    cursor: pointer;
    font-size: 1.5rem;
    line-height: 1;
  }

  .hint {
    margin: 0;
    color: var(--ksd-text-secondary-color);
    font-size: 0.875rem;

    code {
      font-family: ui-monospace, monospace;
      background: var(--ksd-bg-color);
      padding: 0 var(--gr-space-2xs);
      border-radius: 3px;
    }
  }

  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
    overflow-y: auto;
  }

  .row {
    display: flex;
    align-items: center;
    gap: var(--gr-space-sm);
    padding: var(--gr-space-xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
  }

  .row_active {
    border-color: var(--ksd-accent-color);
  }

  .row_dragging {
    opacity: 0.6;
  }

  .handle {
    cursor: grab;
    color: var(--ksd-text-secondary-color);
    user-select: none;
  }

  .swatch {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .layerName {
    flex-shrink: 0;
    text-transform: lowercase;
  }

  .controls {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: var(--gr-space-sm);
  }

  .opacity {
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-size: 0.75rem;
  }

  .muted {
    color: var(--ksd-text-secondary-color);
  }

  .focus {
    padding: 2px var(--gr-space-xs);
    font-size: 0.75rem;
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    color: var(--ksd-text-main-color);
    cursor: pointer;

    &:hover {
      border-color: var(--ksd-accent-color);
    }
  }

  .focus_active {
    background: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
    border-color: var(--ksd-accent-color);
  }

  .footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--gr-space-md);
    padding-top: var(--gr-space-xs);
    border-top: 1px solid var(--ksd-border-color);
  }

  .slice {
    display: flex;
    align-items: center;
    gap: var(--gr-space-xs);
    font-size: 0.875rem;
  }

  .resetBtn {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    background: transparent;
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    color: var(--ksd-text-main-color);
    cursor: pointer;

    &:hover {
      border-color: var(--ksd-accent-color);
    }
  }
</style>
