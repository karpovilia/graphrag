<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, toRaw, ref, watch } from "vue";
import {
  GraphCanvas,
  FORCE_SETTINGS,
  GRAPH_SETTINGS,
  HIGHLIGHT_SETTINGS,
  LINK_OPTIONS,
  LINK_SETTINGS,
  NODE_OPTIONS,
  NODE_SETTINGS,
} from "@krainovsd/graph";
import { zoomIdentity } from "d3-zoom";
import type { RenderGraph } from "@/lib/api";

const props = defineProps<{
  graph: RenderGraph | null;
  focusIds: string[];
  deltaStatus: Record<string, string>;
  /** Multi-selected node ids (shift-click / lasso) — drawn with a dark ring. */
  selectedIds?: string[];
  /** Draw community zones (hulls). When false, communities are hidden. */
  showGroups?: boolean;
  /** When true, data changes gently re-settle the layout; when false the
   *  layout is frozen (existing nodes keep their position, new ones appear in
   *  place). Either way we never re-explode from scratch. */
  autoRelayout?: boolean;
  /** Live force-engine parameters (driven by the Layout panel sliders). */
  layout?: Record<string, number>;
  /** Freeze the layout (no reheat) — used while time-travelling/playing the
   *  timeline so nodes don't jitter; only delta halos update in place. */
  freeze?: boolean;
}>();
const emit = defineEmits<{
  (e: "select-node", id: string | null): void;
  (e: "select-edge", id: string | null): void;
  (e: "select-derived", info: { source: string; target: string; relation: string }): void;
  (e: "toggle-select", id: string): void;
  (e: "select-many", ids: string[]): void;
}>();

const root = ref<HTMLElement | null>(null);
// The engine's generics are heavy; treat the controller loosely in the view.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let controller: any = null;
// timestamp of the last engine node/edge click → suppresses the empty-click clear
let lastHandled = 0;

const DELTA_BORDER: Record<string, string> = {
  born: "#34a853",
  dead: "#ea4335",
  changed: "#fbbc05",
};
// halo colours for the timeline delta grammar (graphrag parity)
const DELTA_HALO: Record<string, string> = {
  born: "#2ca02c",
  changed: "#1f77b4",
};

/** Read the engine's live node positions so we can carry them across a data
 *  change instead of snapping back to (possibly stale) server x/y. */
function currentPositions(): Map<string, { x: number; y: number }> {
  const m = new Map<string, { x: number; y: number }>();
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const d: any = controller?.getData?.call?.(toRaw(controller));
    for (const n of d?.nodes ?? []) {
      if (typeof n.x === "number" && typeof n.y === "number") m.set(n.id, { x: n.x, y: n.y });
    }
  } catch {
    /* engine not ready */
  }
  return m;
}

/** Build engine data. When `preserve`, existing nodes keep their current
 *  rendered position (no jump); new nodes use the server-seeded x/y (the
 *  applier places them near their neighbours). */
function cloneData(preserve = false) {
  const g = props.graph;
  if (!g) return { nodes: [], links: [] };
  const pos = preserve ? currentPositions() : new Map<string, { x: number; y: number }>();
  return {
    nodes: g.graph.nodes.map((n) => {
      const p = pos.get(n.id);
      return { ...n, x: p?.x ?? n.x ?? 0, y: p?.y ?? n.y ?? 0, data: { ...n.data } };
    }),
    links: g.graph.links.map((l) => ({ ...l, data: { ...l.data } })),
  };
}

function nodeOptions() {
  const focus = new Set(props.focusIds);
  const focusing = focus.size > 0;
  const delta = props.deltaStatus;
  const selected = new Set(props.selectedIds ?? []);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (node: any) => {
    const inFocus = focus.has(node.id);
    const dim = focusing && !inFocus;
    const deltaKey = delta[node.id];
    const deltaBorder = deltaKey ? DELTA_BORDER[deltaKey] : undefined;
    const pinned = node.data?.pinned;
    const verified = node.data?.verified;
    const isSel = selected.has(node.id);
    const accent =
      (isSel ? "#ffd400" : undefined) ??
      deltaBorder ??
      (inFocus ? "#1a73e8" : verified ? "#1e8e3e" : pinned ? "#f9ab00" : undefined);
    // Radius is FIXED (nodeRadiusFlexible:false in settings → no link-count
    // inflation). The visible caption is drawn from `text` at `textSize`
    // (NOT labelSize), so set textSize larger than the radius for legibility.
    const r = 2.5 + (node.data?.size ?? 1) * 0.8;
    // keep captions dark+readable even when dimmed (light-grey on the light
    // canvas was invisible → "captions show nothing" after a focus); fade only
    // the opacity, not to nothing.
    const captionColor = "#202124";
    const captionAlpha = dim ? 0.5 : 1;
    return {
      ...NODE_OPTIONS,
      // `color` is supplied here (omitted from NODE_OPTIONS' type).
      color: node.data?.color ?? "#8a94a6",
      radius: r,
      alpha: dim ? 0.22 : NODE_OPTIONS.alpha ?? 1,
      // visible node caption — engine draws `text` at textSize/textShiftY
      text: node.name,
      textVisible: true,
      textSize: 7,
      textShiftY: r + 6,
      textColor: captionColor,
      textAlpha: captionAlpha,
      textWeight: 600,
      // keep label fields in sync for draw paths that read them
      label: node.name,
      labelSize: 7,
      labelColor: captionColor,
      labelAlpha: captionAlpha,
      borderColor: accent ?? NODE_OPTIONS.borderColor,
      borderWidth: isSel ? 3 : accent ? 1.4 : NODE_OPTIONS.borderWidth,
      // ── timeline delta grammar (graphrag parity): a glowing HALO around
      //   born/changed nodes and a STRIKE-THROUGH on dead ones, driven by the
      //   scrubber's deltaStatus. Drawn manually since the package can't.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      nodeExtraDraw(this: any, nn: any, oo: any) {
        if (!deltaKey && !isSel && !inFocus) return;
        const x = nn.x, y = nn.y;
        if (typeof x !== "number" || typeof y !== "number") return;
        const ctx: CanvasRenderingContext2D | null = this?.context ?? null;
        if (!ctx) return;
        const rr = (oo?.radius ?? r) as number;
        // rings are drawn in WORLD coords (scaled by zoom k); floor them to a
        // constant SCREEN size so a highlighted node stays findable when zoomed out.
        const k = (this?.areaTransform?.k ?? 1) as number;
        const ring = (mul: number, minPx: number) => Math.max(rr * mul, minPx / Math.max(k, 0.001));
        const lw = (mul: number, minPx: number) => Math.max(rr * mul, minPx / Math.max(k, 0.001));
        if (isSel) {
          ctx.save();
          ctx.beginPath();
          ctx.arc(x, y, ring(2.6, 18), 0, Math.PI * 2);
          ctx.strokeStyle = "#ffd400";
          ctx.lineWidth = lw(0.7, 2.5);
          ctx.shadowColor = "#ffd400";
          ctx.shadowBlur = 6;
          ctx.stroke();
          ctx.restore();
        } else if (inFocus) {
          ctx.save();
          ctx.beginPath();
          ctx.arc(x, y, ring(2.4, 20), 0, Math.PI * 2);
          ctx.strokeStyle = "#1a73e8";
          ctx.lineWidth = lw(0.7, 3);
          ctx.shadowColor = "#1a73e8";
          ctx.shadowBlur = 8;
          ctx.stroke();
          ctx.restore();
        }
        if (!deltaKey) return;
        if (deltaKey === "dead") {
          ctx.save();
          ctx.beginPath();
          ctx.moveTo(x - rr * 1.5, y + rr * 1.5);
          ctx.lineTo(x + rr * 1.5, y - rr * 1.5);
          ctx.strokeStyle = "#6b7280";
          ctx.lineWidth = Math.max(0.6, rr * 0.4);
          ctx.stroke();
          ctx.restore();
        } else {
          // born → green, changed → blue
          const halo = DELTA_HALO[deltaKey] ?? "#1a73e8";
          ctx.save();
          ctx.globalAlpha = 0.45;
          ctx.beginPath();
          ctx.arc(x, y, rr * 2.2, 0, Math.PI * 2);
          ctx.strokeStyle = halo;
          ctx.lineWidth = Math.max(0.8, rr * 0.6);
          ctx.stroke();
          ctx.restore();
        }
      },
    };
  };
}

function linkOptions() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (link: any) => ({
    ...LINK_OPTIONS,
    width: 0.5,
    // `color`/`arrowColor` are omitted from LINK_OPTIONS' type — supplied here.
    color: link.data?.color ?? "#5b6470",
    arrowColor: link.data?.color ?? "#5b6470",
  });
}

// Force params scale with graph size. The engine's charge has no distance
// cutoff (distanceMax=∞), so a strong chargeStrength that looks great on a tiny
// graph makes a 1000-node graph fly apart to infinity. Big graphs → near-default
// weak charge + short links + stronger centering pull.
function forceSettings() {
  const L = props.layout ?? {};
  const num = (k: string, d: number) => (typeof L[k] === "number" ? (L[k] as number) : d);
  return {
    ...FORCE_SETTINGS,
    linkForce: true,
    chargeForce: true,
    collideForce: true,
    xForce: true,
    yForce: true,
    linkDistance: num("linkDistance", 90),
    linkStrength: num("linkStrength", 1),
    chargeStrength: num("chargeStrength", -320),
    // 0 = no cutoff (∞); the panel exposes this to tame big graphs
    chargeDistanceMax: num("chargeDistanceMax", 0) > 0 ? num("chargeDistanceMax", 0) : undefined,
    collideAdditionalRadius: num("collideAdditionalRadius", 8),
    collideStrength: num("collideStrength", 0.1),
    centerStrength: num("centerStrength", 1),
    xStrength: num("xStrength", 0.1),
    yStrength: num("yStrength", 0.1),
  };
}

/** Re-apply settings and gently reheat so slider changes take visible effect. */
function reheat(alpha = 0.2) {
  if (!controller) return;
  applyOptions();
  try {
    controller.changeData.call(toRaw(controller), cloneData(true), alpha);
    tuneSim();
  } catch {
    /* noop */
  }
}

// Visual-only update (node/link draw options). Does NOT touch forceSettings,
// so selecting/focusing a node never reheats the simulation (no "rotation").
function applyNodeOptions() {
  if (!controller) return;
  try {
    controller.changeSettings.call(toRaw(controller), {
      nodeSettings: { ...NODE_SETTINGS, nodeRadiusFlexible: false, textScaleMin: 0, options: nodeOptions() },
      linkSettings: { ...LINK_SETTINGS, options: linkOptions() },
    });
  } catch {
    /* engine not ready */
  }
}

function applyOptions() {
  if (!controller) return;
  try {
    controller.changeSettings.call(toRaw(controller), {
      nodeSettings: {
        ...NODE_SETTINGS,
        // use our explicit radius instead of inflating by link count
        nodeRadiusFlexible: false,
        // captions visible at any zoom (we draw them ourselves)
        textScaleMin: 0,
        options: nodeOptions(),
      },
      linkSettings: { ...LINK_SETTINGS, options: linkOptions() },
      forceSettings: forceSettings(),
      highlightSettings: HIGHLIGHT_SETTINGS,
      graphSettings: { ...GRAPH_SETTINGS, zoomExtent: [0.05, 12], zoomInitial: 2.2 },
    });
  } catch {
    /* engine not ready */
  }
}

onMounted(() => {
  if (!root.value) return;
  const data = cloneData();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const GC = GraphCanvas as any;
  controller = new GC({
    root: root.value,
    nodes: data.nodes,
    links: data.links,
    graphSettings: { ...GRAPH_SETTINGS, zoomExtent: [0.05, 12], zoomInitial: 2.2 },
    listeners: {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      onClick: (ev: any, node: any, link: any) => {
        if (node || link) lastHandled = Date.now(); // engine hit something → don't let onRootClick clear
        if (node && ev?.shiftKey) emit("toggle-select", node.id);
        else if (node) emit("select-node", node.id);
        else if (link?.data?.derived) emit("select-derived", { source: link.data.from, target: link.data.to, relation: link.data.relation ?? "co_chunk" });
        else if (link) emit("select-edge", link.data?.id ?? null);
        else {
          emit("select-node", null);
          emit("select-many", []); // empty click clears multi-selection
        }
      },
    },
  });
  applyOptions();
  tuneSim();
});

// Calm the layout animation: the engine never sets these, so d3 keeps its
// bouncy defaults (velocityDecay 0.6). More friction + faster cooldown → a
// smooth glide-to-rest instead of frantic jitter.
function tuneSim() {
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const sim: any = (toRaw(controller) as any)?.simulation;
    sim?.velocityDecay?.(0.82);
    sim?.alphaDecay?.(0.045);
    sim?.alphaMin?.(0.01);
  } catch {
    /* engine not ready */
  }
}

onBeforeUnmount(() => {
  try {
    controller?.destroy?.call?.(toRaw(controller));
  } catch {
    /* noop */
  }
  controller = null;
});

watch(
  () => props.graph,
  () => {
    if (!controller) return;
    try {
      // Preserve current positions; gentle reheat when auto-layout is on,
      // zero reheat (frozen) when off or while time-travelling (freeze) — so
      // timeline scrubbing/play only repaints delta halos, no jitter.
      const alpha = props.freeze || props.autoRelayout === false ? 0 : 0.08;
      controller.changeData.call(toRaw(controller), cloneData(true), alpha);
      tuneSim();
    } catch {
      /* noop */
    }
    applyOptions();
  },
);

watch(() => [props.focusIds, props.deltaStatus, props.selectedIds], applyNodeOptions, { deep: true });
// live layout-slider changes → re-apply forces + reheat
watch(() => props.layout, () => reheat(0.25), { deep: true });

// ── freehand lasso: Shift+drag a free-form loop to pick the nodes inside ──
// The engine has no node selection; we capture the pointer path over the canvas
// (capture-phase pointerdown with Shift, preventDefault so d3-zoom doesn't pan),
// then point-in-polygon test each node's screen position. Pointer coords and node
// coords are BOTH in the engine canvas's space (screen = k·world + t) so they line up.
const lasso = ref<{ x: number; y: number }[] | null>(null);
const lassoPath = computed(() => {
  const pts = lasso.value;
  if (!pts || pts.length < 2) return "";
  return "M" + pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join("L") + "Z";
});
// pointer relative to the engine CANVAS (areaRect) — the exact space node screen
// coords live in (screen = k·world + t, relative to the canvas). Using the same
// rect for the lasso points and the node positions guarantees the hit-test lines
// up regardless of how the canvas sits inside its wrapper.
function areaEl(): HTMLElement | null {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return ((toRaw(controller) as any)?.area as HTMLElement | undefined) ?? root.value;
}
function rel(e: MouseEvent) {
  const r = (areaEl() ?? root.value!).getBoundingClientRect();
  return { x: e.clientX - r.left, y: e.clientY - r.top };
}
// d3-zoom (the engine's pan) listens on MOUSE events, so we lasso on mouse
// events too and claim the gesture in the capture phase before it reaches the
// canvas — guarantees the pan never starts while Shift is held.
function onRootDown(e: MouseEvent) {
  if (!e.shiftKey || e.button !== 0 || !root.value) return;
  e.preventDefault();
  e.stopPropagation();
  lasso.value = [rel(e)];
  window.addEventListener("mousemove", onRootMove, true);
  window.addEventListener("mouseup", onRootUp, true);
}
function onRootMove(e: MouseEvent) {
  if (!lasso.value) return;
  const p = rel(e);
  const last = lasso.value[lasso.value.length - 1];
  // only record once moved a few px — keeps the path light
  if (!last || (last.x - p.x) ** 2 + (last.y - p.y) ** 2 >= 9) lasso.value = [...lasso.value, p];
}
function pointInPoly(x: number, y: number, poly: { x: number; y: number }[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i]!.x, yi = poly[i]!.y, xj = poly[j]!.x, yj = poly[j]!.y;
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
// plain click on empty canvas → clear selection (the engine only fires its
// onClick for hit nodes/links, so detect "empty" ourselves via hit-test).
function onRootClick(e: MouseEvent) {
  if (e.shiftKey || !root.value) return;
  if (Date.now() - lastHandled < 150) return; // engine just selected a node/edge — don't clear
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const ctrl: any = toRaw(controller);
    const t = ctrl?.areaTransform;
    const nodes = ctrl?.getData?.call?.(ctrl)?.nodes ?? [];
    if (!t) return;
    const rect = root.value.getBoundingClientRect();
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
    for (const n of nodes) {
      if (typeof n.x !== "number" || typeof n.y !== "number") continue;
      const sx = t.k * n.x + t.x, sy = t.k * n.y + t.y;
      const rad = (2.5 + (n.data?.size ?? 1) * 0.8) * t.k + 6;
      if ((cx - sx) ** 2 + (cy - sy) ** 2 <= rad * rad) return; // clicked a node → let the engine handle it
    }
    emit("select-node", null);
    emit("select-many", []);
  } catch {
    /* engine not ready */
  }
}

function onRootUp() {
  window.removeEventListener("mousemove", onRootMove, true);
  window.removeEventListener("mouseup", onRootUp, true);
  const pts = lasso.value;
  lasso.value = null;
  if (!pts || pts.length < 3) return; // a click / loop too small
  // a lasso just ended → SWALLOW the trailing synthetic click at the window
  // (capture) so it never reaches onRootClick (which would clear the fresh
  // selection) or the engine. One-shot, with a timeout in case no click fires.
  lastHandled = Date.now();
  const swallow = (ev: MouseEvent) => {
    ev.stopPropagation();
    ev.preventDefault();
    window.removeEventListener("click", swallow, true);
    window.clearTimeout(swallowTimer);
  };
  window.addEventListener("click", swallow, true);
  const swallowTimer = window.setTimeout(() => window.removeEventListener("click", swallow, true), 500);
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const ctrl: any = toRaw(controller);
    const t = ctrl?.areaTransform;
    const nodes = ctrl?.getData?.call?.(ctrl)?.nodes ?? [];
    if (!t) return;
    // node screen coords AND the lasso points are both relative to the engine
    // canvas (areaRect, via rel()), so compare directly — no offset needed.
    const hit: string[] = [];
    for (const n of nodes) {
      if (typeof n.x !== "number" || typeof n.y !== "number") continue;
      const sx = t.k * n.x + t.x;
      const sy = t.k * n.y + t.y;
      if (pointInPoly(sx, sy, pts)) hit.push(n.id);
    }
    emit("select-many", hit);
  } catch {
    /* engine not ready */
  }
}

// ── community hulls: draw groups as translucent zones behind labels ──
interface Hull { id: string; name: string; summary: string | null; color: string; kind: "poly" | "circle"; points?: string; cx: number; cy: number; r?: number; memberIds: string[]; }
const hulls = ref<Hull[]>([]);
let hullRaf: number | null = null;

function convexHull(p: { x: number; y: number }[]) {
  if (p.length < 3) return p;
  const s = [...p].sort((a, b) => a.x - b.x || a.y - b.y);
  const cross = (o: any, a: any, b: any) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const lo: any[] = [];
  for (const q of s) { while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q); }
  const up: any[] = [];
  for (let i = s.length - 1; i >= 0; i--) { const q = s[i]; while (up.length >= 2 && cross(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop(); up.push(q); }
  lo.pop(); up.pop(); return lo.concat(up);
}
function updateHulls() {
  hullRaf = requestAnimationFrame(updateHulls);
  const g = props.graph;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const ctrl: any = toRaw(controller);
  const t = ctrl?.areaTransform;
  const data = ctrl?.getData?.call?.(ctrl);
  if (!g || !t || !data || props.showGroups === false) { if (hulls.value.length) hulls.value = []; return; }
  const pos = new Map<string, { x: number; y: number }>();
  for (const n of data.nodes ?? []) if (typeof n.x === "number") pos.set(n.id, { x: t.k * n.x + t.x, y: t.k * n.y + t.y });
  const out: Hull[] = [];
  for (const grp of g.graph.groups ?? []) {
    const pts = grp.memberIds.map((id) => pos.get(id)).filter(Boolean) as { x: number; y: number }[];
    if (!pts.length) continue;
    const cx = pts.reduce((a, p) => a + p.x, 0) / pts.length;
    const cy = pts.reduce((a, p) => a + p.y, 0) / pts.length;
    if (pts.length < 3) {
      const r = Math.max(0, ...pts.map((p) => Math.hypot(p.x - cx, p.y - cy))) + 28;
      out.push({ id: grp.id, name: grp.name, summary: grp.summary, color: grp.color, kind: "circle", cx, cy, r, memberIds: grp.memberIds });
    } else {
      const h = convexHull(pts).map((p) => { const dx = p.x - cx, dy = p.y - cy, d = Math.hypot(dx, dy) || 1; return { x: p.x + (dx / d) * 24, y: p.y + (dy / d) * 24 }; });
      out.push({ id: grp.id, name: grp.name, summary: grp.summary, color: grp.color, kind: "poly", points: h.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" "), cx, cy, memberIds: grp.memberIds });
    }
  }
  hulls.value = out;
}
onMounted(() => { hullRaf = requestAnimationFrame(updateHulls); });
onBeforeUnmount(() => { if (hullRaf != null) cancelAnimationFrame(hullRaf); });

// ── "see what they see": read / apply another participant's worldview ──
function getCamera(): { k: number; x: number; y: number } | null {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const t = (toRaw(controller) as any)?.areaTransform;
  return t ? { k: t.k, x: t.x, y: t.y } : null;
}
function getPositions(): Record<string, [number, number]> {
  const out: Record<string, [number, number]> = {};
  for (const [id, p] of currentPositions()) out[id] = [p.x, p.y];
  return out;
}
function applyView(snap: {
  camera?: { k: number; x: number; y: number } | null;
  positions?: Record<string, [number, number]>;
}): void {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const ctrl: any = toRaw(controller);
  if (!ctrl) return;
  // camera first so the redraw below renders at the new transform; keep d3-zoom's
  // stored transform (__zoom) in sync so the next user gesture continues smoothly
  if (snap.camera) {
    const t = zoomIdentity.translate(snap.camera.x, snap.camera.y).scale(snap.camera.k);
    ctrl.areaTransform = t;
    if (ctrl.area) ctrl.area.__zoom = t;
  }
  // positions: MUTATE the existing node objects in place (don't spread into new
  // ones) — links keep object references to source/target nodes, so creating new
  // node objects would leave edges pointing at the old coordinates. Same refs +
  // alpha 0 → the imported layout holds and edges follow their endpoints.
  try {
    const data = ctrl.getData?.call?.(ctrl) ?? { nodes: [], links: [] };
    if (snap.positions) {
      for (const n of data.nodes ?? []) {
        const p = snap.positions[n.id];
        if (!p) continue;
        n.x = p[0];
        n.y = p[1];
        n.vx = 0;
        n.vy = 0;
        // clear any pin so it sits exactly where imported
        n.fx = null;
        n.fy = null;
      }
    }
    ctrl.changeData?.call?.(ctrl, { nodes: data.nodes ?? [], links: data.links ?? [] }, 0);
  } catch {
    /* engine not ready */
  }
}
defineExpose({ getCamera, getPositions, applyView });
</script>

<template>
  <div class="graph-canvas" @mousedown.capture="onRootDown" @click="onRootClick">
    <!-- the engine owns ONLY this div (it injects its <canvas> here). Vue-managed
         overlays live OUTSIDE it as siblings, so Vue never patches DOM children
         into an element the engine also mutates (that caused insertBefore-null). -->
    <div ref="root" class="graph-engine" />
    <svg class="hulls" v-if="hulls.length">
      <g
        v-for="h in hulls"
        :key="h.id"
        class="hull"
        @click="emit('select-many', h.memberIds)"
      >
        <title>{{ h.name }}{{ h.summary ? " — " + h.summary : "" }}</title>
        <polygon v-if="h.kind === 'poly'" :points="h.points" :fill="h.color" fill-opacity="0.1" :stroke="h.color" stroke-opacity="0.5" stroke-width="2" />
        <circle v-else :cx="h.cx" :cy="h.cy" :r="h.r" :fill="h.color" fill-opacity="0.1" :stroke="h.color" stroke-opacity="0.5" stroke-width="2" />
        <text :x="h.cx" :y="h.cy" :fill="h.color" class="hull-label">{{ h.name }}</text>
      </g>
    </svg>
    <svg v-if="lassoPath" class="lasso-svg">
      <path :d="lassoPath" class="lasso" />
    </svg>
  </div>
</template>

<style scoped>
.graph-canvas {
  width: 100%;
  height: 100%;
  position: relative;
  background: var(--gc-canvas-bg, #0f1115);
}
.graph-engine {
  position: absolute;
  inset: 0;
  z-index: 1;
}
.lasso-svg {
  position: absolute;
  inset: 0;
  z-index: 5;
  width: 100%;
  height: 100%;
  pointer-events: none;
  overflow: visible;
}
.lasso {
  fill: rgba(26, 115, 232, 0.12);
  stroke: var(--gc-accent, #1a73e8);
  stroke-width: 1.5;
  stroke-dasharray: 5 3;
}
.hulls {
  position: absolute;
  inset: 0;
  z-index: 3;
  width: 100%;
  height: 100%;
  pointer-events: none;
  overflow: visible;
}
.hull-label {
  font-size: 11px;
  font-weight: 600;
  text-anchor: middle;
  opacity: 0.85;
  pointer-events: auto;
  cursor: pointer;
}
/* clickable outline (select members) — but the interior lets node clicks through */
.hull polygon,
.hull circle {
  pointer-events: stroke;
  cursor: pointer;
  transition: fill-opacity 0.1s, stroke-opacity 0.1s;
}
.hull:hover polygon,
.hull:hover circle {
  fill-opacity: 0.18;
  stroke-opacity: 0.9;
}
.hull:hover .hull-label {
  opacity: 1;
}
</style>
