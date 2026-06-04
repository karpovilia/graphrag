<script setup lang="ts">
  // §2.1 timeline scrubber — the axis under the canvas. Headless (mirrors
  // LayerMap): it owns NO fetching, just emits the selected instant or
  // range. The host (use-temporal-window) does the at()/diff() calls.
  //
  // Modes:
  //   instant — single draggable handle, emits t (ISO string)
  //   diff    — two-handle range, emits [t_a, t_b]
  // Ticks: one per IngestionEvent, positioned by axis time. Keyboard:
  // ←/→ step the active handle between ticks, space toggles play (instant
  // mode steps t forward via rAF). Debounced emits live in the host.

  import { computed, onBeforeUnmount, ref, watch } from "vue";
  import { useI18n } from "vue-i18n";

  import type { IngestionEvent, TimeAxis } from "@/entities/api";

  const { t: tr } = useI18n();

  type Props = {
    events: IngestionEvent[];
    axis: TimeAxis;
    mode: "instant" | "diff";
    playing?: boolean;
    /** How many entities predate the timeline (born before the first event /
     * timeless). Renders a leading "⋯" genesis cell that selects them. */
    genesisCount?: number;
  };

  const props = withDefaults(defineProps<Props>(), { playing: false, genesisCount: 0 });

  // modelValue: ISO string (instant) or [t_a, t_b] (diff).
  const model = defineModel<string | [string, string] | null>({ default: null });
  const emit = defineEmits<{
    (e: "update:playing", value: boolean): void;
    /** User clicked the leading genesis ("⋯") cell — select the entities
     * that existed before the timeline begins. */
    (e: "select-genesis"): void;
  }>();

  // Sorted event times (ms epoch) along the active axis. `tx` sorts by
  // ingested_at, `valid` by event_time.
  const times = computed<number[]>(() => {
    const field = props.axis === "valid" ? "event_time" : "ingested_at";
    return props.events
      .map((ev) => Date.parse(ev[field]))
      .filter((n) => !Number.isNaN(n))
      .sort((a, b) => a - b);
  });

  const minT = computed(() => times.value[0] ?? 0);
  const maxT = computed(() => times.value[times.value.length - 1] ?? 1);
  const span = computed(() => Math.max(1, maxT.value - minT.value));

  function pct(ms: number): number {
    return ((ms - minT.value) / span.value) * 100;
  }

  function evTime(ev: IngestionEvent): number {
    return Date.parse(props.axis === "valid" ? ev.event_time : ev.ingested_at);
  }

  // Activity heatmap: each bucket is a full-height cell whose colour
  // intensity ∝ event_count, normalised to the busiest bucket — so the eye
  // reads "where a lot happened vs little" along the axis.
  const maxCount = computed(() =>
    Math.max(1, ...props.events.map((ev) => ev.event_count ?? 0)),
  );
  // Events laid out left→right by the active axis (cells must tile in order).
  const sortedEvents = computed<IngestionEvent[]>(() =>
    [...props.events].sort((a, b) => evTime(a) - evTime(b)),
  );
  function cellLeftPct(i: number): number {
    return pct(evTime(sortedEvents.value[i]!));
  }
  function cellWidthPct(i: number): number {
    const arr = sortedEvents.value;
    const next = i < arr.length - 1 ? pct(evTime(arr[i + 1]!)) : 100;
    return Math.max(0.5, next - cellLeftPct(i));
  }
  function heat(ev: IngestionEvent): string {
    const r = Math.min(1, (ev.event_count ?? 0) / maxCount.value);
    // sequential blue ramp (light = quiet, dark = busy)
    return `rgba(31, 119, 180, ${(0.06 + 0.9 * r).toFixed(3)})`;
  }

  // Total events inside the currently-selected period (diff) — the schematic
  // "how much happened in this window" readout.
  const eventsInRange = computed<number>(() => {
    if (props.mode !== "diff") return 0;
    const lo = Math.min(handleA.value, handleB.value);
    const hi = Math.max(handleA.value, handleB.value);
    return props.events.reduce((sum, ev) => {
      const t = evTime(ev);
      return t >= lo && t <= hi ? sum + (ev.event_count ?? 0) : sum;
    }, 0);
  });

  // Current handle position(s) in ms. Default to the extremes.
  const handleA = ref<number>(minT.value);
  const handleB = ref<number>(maxT.value);

  // Seed handles from model / event range when events arrive.
  watch(
    () => [props.events, props.mode] as const,
    () => {
      if (!times.value.length) return;
      if (props.mode === "instant") {
        handleA.value = parseModelInstant() ?? maxT.value;
      } else {
        const r = parseModelRange();
        handleA.value = r?.[0] ?? minT.value;
        handleB.value = r?.[1] ?? maxT.value;
      }
    },
    { immediate: true, deep: true },
  );

  function parseModelInstant(): number | null {
    if (typeof model.value === "string") {
      const ms = Date.parse(model.value);
      return Number.isNaN(ms) ? null : ms;
    }
    return null;
  }
  function parseModelRange(): [number, number] | null {
    if (Array.isArray(model.value)) {
      const a = Date.parse(model.value[0]);
      const b = Date.parse(model.value[1]);
      if (Number.isNaN(a) || Number.isNaN(b)) return null;
      return [a, b];
    }
    return null;
  }

  function emitModel() {
    if (props.mode === "instant") {
      model.value = new Date(handleA.value).toISOString();
    } else {
      const lo = Math.min(handleA.value, handleB.value);
      const hi = Math.max(handleA.value, handleB.value);
      model.value = [new Date(lo).toISOString(), new Date(hi).toISOString()];
    }
  }

  // Drag handling on the track.
  const trackRef = ref<HTMLElement | null>(null);
  const dragging = ref<"a" | "b" | null>(null);

  function msFromClientX(clientX: number): number {
    const el = trackRef.value;
    if (!el) return handleA.value;
    const rect = el.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    return minT.value + ratio * span.value;
  }

  function startDrag(which: "a" | "b", e: PointerEvent) {
    dragging.value = which;
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
  }

  function onPointerMove(e: PointerEvent) {
    if (!dragging.value) return;
    const ms = msFromClientX(e.clientX);
    if (dragging.value === "a") handleA.value = ms;
    else handleB.value = ms;
    emitModel();
  }

  function onPointerUp() {
    dragging.value = null;
  }

  function onTrackClick(e: MouseEvent) {
    if (dragging.value) return;
    const ms = msFromClientX(e.clientX);
    if (props.mode === "instant") {
      handleA.value = ms;
    } else {
      // Move the nearer handle.
      const da = Math.abs(ms - handleA.value);
      const db = Math.abs(ms - handleB.value);
      if (da <= db) handleA.value = ms;
      else handleB.value = ms;
    }
    emitModel();
  }

  // Keyboard stepping between ticks.
  function stepHandle(dir: 1 | -1) {
    const ts = times.value;
    if (!ts.length) return;
    const cur = handleA.value;
    // Find the next tick strictly in `dir`.
    let next = cur;
    if (dir === 1) {
      next = ts.find((x) => x > cur + 1) ?? ts[ts.length - 1]!;
    } else {
      const before = ts.filter((x) => x < cur - 1);
      next = before.length ? before[before.length - 1]! : ts[0]!;
    }
    handleA.value = next;
    emitModel();
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === "ArrowRight") {
      stepHandle(1);
      e.preventDefault();
    } else if (e.key === "ArrowLeft") {
      stepHandle(-1);
      e.preventDefault();
    } else if (e.key === " ") {
      togglePlay();
      e.preventDefault();
    }
  }

  // Play stepping (instant mode): advance t through the ticks via rAF.
  let rafId: number | null = null;
  let lastStep = 0;
  const STEP_MS = 800;

  function tick(ts: number) {
    if (!props.playing) return;
    if (ts - lastStep >= STEP_MS) {
      lastStep = ts;
      const arr = times.value;
      const i = arr.findIndex((x) => x > handleA.value + 1);
      if (i === -1) {
        emit("update:playing", false);
        return;
      }
      handleA.value = arr[i]!;
      emitModel();
    }
    rafId = requestAnimationFrame(tick);
  }

  function togglePlay() {
    if (props.mode !== "instant") return;
    emit("update:playing", !props.playing);
  }

  watch(
    () => props.playing,
    (p) => {
      if (p) {
        lastStep = 0;
        rafId = requestAnimationFrame(tick);
      } else if (rafId !== null) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
    },
  );

  onBeforeUnmount(() => {
    if (rafId !== null) cancelAnimationFrame(rafId);
  });

  const handleAPct = computed(() => pct(handleA.value));
  const handleBPct = computed(() => pct(handleB.value));

  function eventLabel(ev: IngestionEvent): string {
    const field = props.axis === "valid" ? ev.event_time : ev.ingested_at;
    const d = new Date(field);
    return `${ev.label} — ${Number.isNaN(d.getTime()) ? field : d.toLocaleDateString()}`;
  }
</script>

<template>
  <div
    :class="$style.scrubber"
    tabindex="0"
    role="slider"
    :aria-valuemin="minT"
    :aria-valuemax="maxT"
    :aria-valuenow="handleA"
    :aria-label="tr('timeline.scrubAria')"
    @keydown="onKeydown"
    @pointermove="onPointerMove"
    @pointerup="onPointerUp"
  >
    <button
      v-if="mode === 'instant'"
      type="button"
      :class="[$style.play, playing ? $style.play_active : '']"
      :title="tr('timeline.playTip')"
      @click="togglePlay"
    >
      {{ playing ? "⏸" : "▶" }}
    </button>

    <button
      v-if="genesisCount > 0"
      type="button"
      :class="$style.genesis"
      data-testid="timeline-genesis"
      :title="tr('timeline.genesisTip', { n: genesisCount })"
      @click="emit('select-genesis')"
    >
      ⋯
    </button>

    <div
      ref="trackRef"
      data-testid="timeline-track"
      :class="$style.track"
      @click="onTrackClick"
    >
      <!-- range fill (diff mode) -->
      <div
        v-if="mode === 'diff'"
        :class="$style.range"
        :style="{
          left: `${Math.min(handleAPct, handleBPct)}%`,
          width: `${Math.abs(handleBPct - handleAPct)}%`,
        }"
      />

      <!-- activity heatmap: one cell per bucket, colour intensity ∝ count -->
      <span
        v-for="(ev, i) in sortedEvents"
        :key="ev.id"
        data-testid="timeline-tick"
        :class="$style.cell"
        :style="{
          left: `${cellLeftPct(i)}%`,
          width: `${cellWidthPct(i)}%`,
          background: heat(ev),
        }"
        :title="`${eventLabel(ev)} · ${ev.event_count} эв.`"
        :data-i="i"
        :data-label="ev.label"
        :data-left="cellLeftPct(i)"
        :data-count="ev.event_count"
      />

      <!-- handle A -->
      <span
        :class="$style.handle"
        :style="{ left: `${handleAPct}%` }"
        @pointerdown="startDrag('a', $event)"
      />
      <!-- handle B (diff only) -->
      <span
        v-if="mode === 'diff'"
        :class="$style.handle"
        :style="{ left: `${handleBPct}%` }"
        @pointerdown="startDrag('b', $event)"
      />
    </div>

    <span :class="$style.readout">
      <template v-if="mode === 'instant'">
        {{ new Date(handleA).toLocaleDateString() }}
      </template>
      <template v-else>
        {{ new Date(Math.min(handleA, handleB)).toLocaleDateString() }}
        →
        {{ new Date(Math.max(handleA, handleB)).toLocaleDateString() }}
        · {{ eventsInRange }} эв.
      </template>
    </span>
  </div>
</template>

<style lang="scss" module>
  .scrubber {
    display: flex;
    align-items: center;
    gap: var(--gr-space-sm);
    padding: var(--gr-space-xs) var(--gr-space-md);
    outline: none;

    &:focus-visible {
      box-shadow: inset 0 0 0 2px var(--ksd-accent-color);
    }
  }

  .play {
    flex-shrink: 0;
    width: 28px;
    height: 28px;
    border: 1px solid var(--ksd-border-color);
    border-radius: 50%;
    background: transparent;
    cursor: pointer;
    color: var(--ksd-text-main-color);
  }

  .play_active {
    background: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
    border-color: var(--ksd-accent-color);
  }

  .genesis {
    flex-shrink: 0;
    width: 28px;
    height: 28px;
    border: 1px dashed var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    cursor: pointer;
    color: var(--ksd-text-secondary-color, var(--ksd-text-main-color));
    font-size: 1.1rem;
    line-height: 1;

    &:hover {
      border-color: var(--ksd-accent-color);
      color: var(--ksd-accent-color);
    }
  }

  .track {
    position: relative;
    flex: 1;
    height: 48px;
    background: var(--ksd-card-bg-color);
    border-radius: var(--gr-radius-sm);
    cursor: pointer;
  }

  // Translucent highlight of the selected period (range/diff mode).
  .range {
    position: absolute;
    top: 0;
    bottom: 0;
    background: rgba(31, 119, 180, 0.12);
    border-left: 1px solid rgba(31, 119, 180, 0.5);
    border-right: 1px solid rgba(31, 119, 180, 0.5);
    pointer-events: none;
  }

  // Activity heatmap cell — one per bucket, full height, colour ∝ count.
  .cell {
    position: absolute;
    top: 0;
    bottom: 0;
    border-right: 1px solid var(--ksd-bg-color);
    pointer-events: auto;
  }

  .handle {
    position: absolute;
    top: 50%;
    width: 14px;
    height: 14px;
    margin-left: -7px;
    transform: translateY(-50%);
    background: var(--ksd-accent-color);
    border: 2px solid var(--ksd-bg-color);
    border-radius: 50%;
    cursor: grab;
    box-shadow: var(--gr-shadow-sm);
    touch-action: none;

    &:active {
      cursor: grabbing;
    }
  }

  .readout {
    flex-shrink: 0;
    font-size: 0.75rem;
    color: var(--ksd-text-secondary-color);
    min-width: 9rem;
    text-align: right;
  }
</style>
