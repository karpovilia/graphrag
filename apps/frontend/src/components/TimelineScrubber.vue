<script setup lang="ts">
// Two-handle window scrubber. Two draggable markers define [from, to]; the
// canvas shows only nodes born inside the window (host applies the filter).
// Background = activity histogram (height ∝ activity, born/changed/dead). Drag
// either handle or the band; click the track to move the nearer handle.
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { Bucket, QuantSegment, TimelineEvent } from "@/lib/api";

const { t } = useI18n();

const props = defineProps<{
  events: TimelineEvent[];
  axis: "tx" | "valid";
  from: string | null;
  to: string | null;
  bucket: Bucket | "auto";
  segments: QuantSegment[];
  genesisCount?: number;
}>();
const emit = defineEmits<{
  (e: "update:axis", v: "tx" | "valid"): void;
  (e: "select-genesis"): void;
  (e: "window", v: { from: string | null; to: string | null }): void;
  (e: "update:bucket", v: Bucket | "auto"): void;
  (e: "add-segment", v: QuantSegment): void;
  (e: "remove-segment", i: number): void;
}>();
const BUCKETS: (Bucket | "auto")[] = ["auto", "year", "quarter", "month", "week", "day", "hour", "instant"];
const windowSel = computed(() => props.from != null || props.to != null);
function quantizeWindow() {
  const b = props.bucket === "auto" ? "month" : props.bucket;
  emit("add-segment", { from: props.from, to: props.to, bucket: b });
}

const sorted = computed(() => [...props.events].sort((a, b) => Date.parse(a.at) - Date.parse(b.at)));
const times = computed(() => sorted.value.map((e) => Date.parse(e.at)));
const minT = computed(() => times.value[0] ?? 0);
const maxT = computed(() => times.value[times.value.length - 1] ?? 1);
const span = computed(() => Math.max(1, maxT.value - minT.value));
const pct = (ms: number) => ((ms - minT.value) / span.value) * 100;

const total = (e: TimelineEvent) => (e.bornCount + e.deadCount + e.opCount) || e.eventCount || 0;
const maxTotal = computed(() => Math.max(1, ...sorted.value.map(total)));
function cellLeft(i: number) { return pct(times.value[i]!); }
function cellWidth(i: number) {
  const next = i < times.value.length - 1 ? pct(times.value[i + 1]!) : 100;
  return Math.max(0.8, next - cellLeft(i) - 0.3);
}
function barHeight(e: TimelineEvent) {
  return `${(8 + 88 * Math.sqrt(total(e) / maxTotal.value)).toFixed(1)}%`;
}
const seg = (e: TimelineEvent, k: "bornCount" | "opCount" | "deadCount") => {
  const tot = (e.bornCount + e.opCount + e.deadCount) || 1;
  return `${((e[k] / tot) * 100).toFixed(1)}%`;
};

// handle positions (ms)
const hA = ref(minT.value);
const hB = ref(maxT.value);
watch(
  () => [props.events, props.from, props.to] as const,
  () => {
    hA.value = props.from ? Date.parse(props.from) : minT.value;
    hB.value = props.to ? Date.parse(props.to) : maxT.value;
  },
  { immediate: true, deep: true },
);
const aPct = computed(() => pct(Math.min(hA.value, hB.value)));
const bPct = computed(() => pct(Math.max(hA.value, hB.value)));
const fmt = (ms: number) => { const d = new Date(ms); return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(); };

const trackRef = ref<HTMLElement | null>(null);
const drag = ref<"a" | "b" | "band" | "">("");
let bandGrab = 0;
function msFromX(clientX: number) {
  const el = trackRef.value;
  if (!el) return minT.value;
  const r = el.getBoundingClientRect();
  return minT.value + Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * span.value;
}
function down(which: "a" | "b" | "band", e: PointerEvent) {
  drag.value = which;
  (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
  if (which === "band") bandGrab = msFromX(e.clientX);
  e.stopPropagation();
}
function move(e: PointerEvent) {
  if (!drag.value) return;
  const ms = msFromX(e.clientX);
  if (drag.value === "a") hA.value = Math.min(ms, hB.value);
  else if (drag.value === "b") hB.value = Math.max(ms, hA.value);
  else if (drag.value === "band") {
    const d = ms - bandGrab; bandGrab = ms;
    const lo = Math.min(hA.value, hB.value), hi = Math.max(hA.value, hB.value);
    const nlo = Math.max(minT.value, lo + d), nhi = Math.min(maxT.value, hi + d);
    if (nhi - nlo === hi - lo) { hA.value = nlo; hB.value = nhi; }
  }
}
function emitWindow() {
  const lo = Math.min(hA.value, hB.value), hi = Math.max(hA.value, hB.value);
  emit("window", {
    from: lo <= minT.value + 1 ? null : new Date(lo).toISOString(),
    to: hi >= maxT.value - 1 ? null : new Date(hi).toISOString(),
  });
}
function up() {
  if (drag.value) { drag.value = ""; emitWindow(); }
}
function onTrackClick(e: MouseEvent) {
  if (drag.value) return;
  const ms = msFromX(e.clientX);
  if (Math.abs(ms - hA.value) <= Math.abs(ms - hB.value)) hA.value = Math.min(ms, hB.value);
  else hB.value = Math.max(ms, hA.value);
  emitWindow();
}
function reset() { hA.value = minT.value; hB.value = maxT.value; emit("window", { from: null, to: null }); }

function cellTitle(e: TimelineEvent) {
  const d = new Date(e.at);
  const when = Number.isNaN(d.getTime()) ? e.at : d.toLocaleString();
  const parts: string[] = [];
  if (e.bornCount) parts.push(`+${e.bornCount}`);
  if (e.opCount) parts.push(`✎${e.opCount}`);
  if (e.deadCount) parts.push(`−${e.deadCount}`);
  return `${when} · ${parts.join("  ") || "—"}`;
}
const windowed = computed(() => props.from != null || props.to != null);
</script>

<template>
  <div class="scrubber" @pointermove="move" @pointerup="up">
    <button v-if="(genesisCount ?? 0) > 0" class="genesis" :title="t('genesis', { n: genesisCount })" @click="emit('select-genesis')">⋯</button>

    <div v-if="sorted.length" class="track-wrap">
      <div ref="trackRef" class="track" :title="t('rangeHint')" @click="onTrackClick">
        <div class="baseline" />
        <div
          v-for="(ev, i) in sorted"
          :key="ev.id"
          class="bar"
          :style="{ left: `${cellLeft(i)}%`, width: `${cellWidth(i)}%`, height: barHeight(ev) }"
          :title="cellTitle(ev)"
        >
          <span v-if="ev.deadCount" class="sg dead" :style="{ height: seg(ev, 'deadCount') }" />
          <span v-if="ev.opCount" class="sg op" :style="{ height: seg(ev, 'opCount') }" />
          <span v-if="ev.bornCount" class="sg born" :style="{ height: seg(ev, 'bornCount') }" />
          <span v-if="!ev.bornCount && !ev.opCount && !ev.deadCount" class="sg flat" />
        </div>
        <!-- dim outside-window regions -->
        <div class="mask" :style="{ left: '0%', width: `${aPct}%` }" />
        <div class="mask" :style="{ left: `${bPct}%`, right: '0' }" />
        <!-- selected band (draggable) -->
        <div class="band" :style="{ left: `${aPct}%`, width: `${Math.max(0, bPct - aPct)}%` }" @pointerdown="down('band', $event)" />
        <!-- handles -->
        <div class="handle" :style="{ left: `${aPct}%` }" @pointerdown="down('a', $event)"><span class="knob" /></div>
        <div class="handle" :style="{ left: `${bPct}%` }" @pointerdown="down('b', $event)"><span class="knob" /></div>
      </div>
      <div class="ticks">
        <span>{{ fmt(Math.min(hA, hB)) }}</span>
        <span class="mid">{{ windowed ? t("windowed") : fmt(minT + span / 2) }}</span>
        <span>{{ fmt(Math.max(hA, hB)) }}</span>
      </div>
    </div>
    <span v-else class="empty">{{ t("noAxisEvents") }}</span>

    <button v-if="windowed" class="reset" :title="t('reset')" @click="reset">✕</button>

    <!-- quantization: global bucket + per-interval overrides -->
    <div class="quant">
      <select class="qsel" :value="bucket" :title="t('quantize')" @change="emit('update:bucket', ($event.target as HTMLSelectElement).value as Bucket | 'auto')">
        <option v-for="b in BUCKETS" :key="b" :value="b">{{ t('q_' + b) }}</option>
      </select>
      <button v-if="windowSel" class="qseg-add" :title="t('quantizeInterval')" @click="quantizeWindow">⏲＋</button>
      <span v-for="(s, i) in segments" :key="i" class="qseg" :title="t('removeSeg')" @click="emit('remove-segment', i)">{{ t('q_' + s.bucket) }} ✕</span>
    </div>

    <div class="axis">
      <button :class="{ active: axis === 'tx' }" :title="t('axisTxTip')" @click="emit('update:axis', 'tx')">{{ t("axisTx") }}</button>
      <button :class="{ active: axis === 'valid' }" :title="t('axisValidTip')" @click="emit('update:axis', 'valid')">{{ t("axisValid") }}</button>
    </div>
  </div>
</template>

<style scoped>
.scrubber { display: flex; align-items: center; gap: 10px; outline: none; flex: 1; min-width: 0; width: 100%; }
.empty { flex: 1; font-size: 12px; color: var(--gc-muted, #80868b); font-style: italic; }
.genesis { flex-shrink: 0; width: 24px; height: 24px; border: 1px dashed var(--gc-border); background: var(--gc-card); color: var(--gc-fg); cursor: pointer; border-radius: 7px; font-size: 16px; padding: 0; }
.genesis:hover { border-color: var(--gc-accent); color: var(--gc-accent); }
.track-wrap { flex: 1; min-width: 200px; display: flex; flex-direction: column; gap: 2px; }
.track { position: relative; height: 30px; background: linear-gradient(180deg, var(--gc-bg, #f6f7f9), var(--gc-card)); border: 1px solid var(--gc-border); border-radius: 6px; cursor: pointer; overflow: hidden; }
.baseline { position: absolute; left: 0; right: 0; bottom: 0; height: 1px; background: var(--gc-border); }
.bar { position: absolute; bottom: 0; display: flex; flex-direction: column; border-radius: 2px 2px 0 0; overflow: hidden; opacity: 0.9; }
.sg { display: block; width: 100%; }
.sg.born { background: #34a853; } .sg.op { background: #f9ab00; } .sg.dead { background: #ea4335; }
.sg.flat { background: #1a73e8; flex: 1; opacity: 0.5; }
.mask { position: absolute; top: 0; bottom: 0; background: rgba(120,130,140,0.28); pointer-events: none; }
.band { position: absolute; top: 0; bottom: 0; background: rgba(26,115,232,0.10); border-left: 2px solid var(--gc-accent); border-right: 2px solid var(--gc-accent); cursor: grab; }
.band:active { cursor: grabbing; }
.handle { position: absolute; top: 0; bottom: 0; width: 0; transform: translateX(-1px); }
.knob { position: absolute; top: 50%; left: -6px; transform: translateY(-50%); width: 12px; height: 12px; background: var(--gc-accent); border: 2px solid #fff; border-radius: 50%; box-shadow: 0 1px 4px rgba(0,0,0,0.35); cursor: ew-resize; }
.ticks { display: flex; justify-content: space-between; font-size: 10px; color: var(--gc-muted, #9aa0a6); padding: 0 2px; }
.ticks .mid { opacity: 0.85; color: var(--gc-accent); }
.reset { flex-shrink: 0; width: 22px; height: 22px; border: 1px solid var(--gc-border); background: var(--gc-card); color: var(--gc-muted, #80868b); border-radius: 50%; cursor: pointer; font-size: 11px; padding: 0; }
.reset:hover { color: #c5221f; border-color: #c5221f; }
.quant { display: flex; align-items: center; gap: 4px; flex-shrink: 0; flex-wrap: wrap; max-width: 240px; }
.qsel { border: 1px solid var(--gc-border); background: var(--gc-card); color: var(--gc-fg); border-radius: 6px; font-size: 11px; padding: 3px 4px; }
.qseg-add { border: 1px solid var(--gc-border); background: var(--gc-card); color: var(--gc-fg); border-radius: 6px; cursor: pointer; font-size: 11px; padding: 3px 6px; }
.qseg-add:hover { border-color: var(--gc-accent); color: var(--gc-accent); }
.qseg { border: 1px solid var(--gc-accent); color: var(--gc-accent); border-radius: 10px; padding: 1px 7px; font-size: 10px; cursor: pointer; }
.axis { display: flex; flex-shrink: 0; }
.axis button { border: 1px solid var(--gc-border); background: var(--gc-card); color: var(--gc-fg); padding: 4px 9px; cursor: pointer; font-size: 11px; }
.axis button:first-child { border-radius: 6px 0 0 6px; }
.axis button:last-child { border-radius: 0 6px 6px 0; border-left: none; }
.axis button.active { background: var(--gc-accent); border-color: var(--gc-accent); color: #fff; }
</style>
