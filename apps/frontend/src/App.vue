<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue";
import type { ViewSnapshot } from "@graphcraft/shared";
import { useI18n } from "vue-i18n";
import GraphView from "@/components/GraphView.vue";
import DecisionModal from "@/components/DecisionModal.vue";
import SuggestionPanel from "@/components/SuggestionPanel.vue";
import JournalPanel from "@/components/JournalPanel.vue";
import RagPanel from "@/components/RagPanel.vue";
import TimelineScrubber from "@/components/TimelineScrubber.vue";
import Inspector, { type CardConfig } from "@/components/Inspector.vue";
import DossierWindow from "@/components/DossierWindow.vue";
import SkillPanel from "@/components/SkillPanel.vue";
import GraphsHome from "@/components/GraphsHome.vue";
import { api, type Fact } from "@/lib/api";
import { useRoom } from "@/composables/useRoom";

const { t, locale } = useI18n();

const rawGraph = new URLSearchParams(location.search).get("graph");
const onHome = !rawGraph;
const graphId = rawGraph ?? "";
function openGraph(id: string) {
  location.href = `${location.pathname}?graph=${encodeURIComponent(id)}`;
}
function goHome() {
  location.href = location.pathname;
}
const actorName = ref(
  localStorage.getItem("gc:actor") ?? `guest-${Math.random().toString(36).slice(2, 6)}`,
);
function saveActor() {
  localStorage.setItem("gc:actor", actorName.value);
}

const room = useRoom(graphId, () => actorName.value);
const tab = ref<"suggestions" | "journal" | "skills">("suggestions");
const selectedNodeId = ref<string | null>(null);
const selectedEdgeId = ref<string | null>(null);
const hoverIds = ref<string[]>([]);

// selected Batagelj projection edge → show its composition (shared intermediaries)
const derivedSel = ref<{ source: string; target: string; relation: string } | null>(null);

// ── card navigation breadcrumbs (drill from one entity to the next) ──
const navTrail = ref<{ id: string; name: string }[]>([]);
const nodeName = (id: string) => room.graph.value?.graph.nodes.find((n) => n.id === id)?.name ?? id;
function pushTrail(id: string) {
  const last = navTrail.value[navTrail.value.length - 1];
  if (last?.id === id) return;
  navTrail.value = [...navTrail.value, { id, name: nodeName(id) }].slice(-12);
}
function navTo(i: number) {
  const item = navTrail.value[i];
  if (!item) return;
  navTrail.value = navTrail.value.slice(0, i + 1);
  selectedNodeId.value = item.id;
  selectedEdgeId.value = null;
  derivedSel.value = null;
  if (dossierNodeId.value) dossierNodeId.value = item.id;
}
function navBack() { if (navTrail.value.length > 1) navTo(navTrail.value.length - 2); }

function selectNode(id: string | null) {
  selectedNodeId.value = id;
  selectedEdgeId.value = null;
  derivedSel.value = null;
  if (id) pushTrail(id);
  else { navTrail.value = []; hoverIds.value = []; room.clearFocus(); } // empty click clears focus dimming too
}
function selectEdge(id: string | null) {
  selectedEdgeId.value = id;
  selectedNodeId.value = null;
  derivedSel.value = null;
}
function selectDerived(info: { source: string; target: string; relation: string }) {
  derivedSel.value = info;
  selectedNodeId.value = null;
  selectedEdgeId.value = null;
}
function closeInspector() {
  selectedNodeId.value = null;
  selectedEdgeId.value = null;
  derivedSel.value = null;
  navTrail.value = [];
}

// Curation agents: LLM dedup (catches transliteration/nickname dupes) + per-type skill suggestions.
const agentBusy = ref("");
async function runDedupLlm() {
  agentBusy.value = "dedup-llm";
  try { await room.actions.runAgent("dedup-llm"); } finally { agentBusy.value = ""; }
}
async function suggestSkills() {
  agentBusy.value = "skills";
  try { await api.suggestSkills(graphId); skills.value = await api.listSkills(graphId); } catch { /* */ } finally { agentBusy.value = ""; }
}

// ── card fact config + analysis window ──
const cardConfig = ref<CardConfig>(
  JSON.parse(localStorage.getItem("gc:cardConfig") || "null") ?? {
    minConfidence: 0.9,
    verifiedOnly: false,
    showRelations: true,
    showAttributes: true,
  },
);
// expanded dossier (two-pane, schema-driven) opened from the compact card
const dossierNodeId = ref<string | null>(null);
function onDossierOp(op: string, payload: Record<string, unknown>) {
  void room.actions.applyOp(op, payload);
}

// ── multi-selection (shift-click / lasso) + skills menu ──
const multiSelected = ref<string[]>([]);
const skills = ref<{ id: string; name: string }[]>([]);
// nodes drawn with the dark selection ring = multi-selection ∪ single click
const highlightedIds = computed(() => {
  const s = new Set(multiSelected.value);
  if (selectedNodeId.value) s.add(selectedNodeId.value);
  return [...s];
});
function toggleSelect(id: string) {
  // first shift-click extends from the currently single-selected node
  let base = multiSelected.value;
  if (base.length === 0 && selectedNodeId.value && selectedNodeId.value !== id) base = [selectedNodeId.value];
  const i = base.indexOf(id);
  multiSelected.value = i >= 0 ? base.filter((x) => x !== id) : [...base, id];
}
function selectMany(ids: string[]) {
  multiSelected.value = ids;
}
// 2–4 multi-selected nodes → a full card for each. More than 4 → collapse to a
// stack of "spines" (name + ✕), up to 20, so they stay manageable. Closing a
// card/spine deselects that node. Single selection / edges keep the rich Inspector.
const FULL_CARDS = 4;
const SPINE_LIMIT = 20;
const cardIds = computed(() =>
  multiSelected.value.length >= 2 && multiSelected.value.length <= FULL_CARDS ? multiSelected.value : [],
);
const spineIds = computed(() =>
  multiSelected.value.length > FULL_CARDS ? multiSelected.value.slice(0, SPINE_LIMIT) : [],
);
const spineOverflow = computed(() => Math.max(0, multiSelected.value.length - SPINE_LIMIT));
const nameOf = (id: string) => room.graph.value?.graph.nodes.find((n) => n.id === id)?.name ?? id;
function closeCard(id: string) {
  multiSelected.value = multiSelected.value.filter((x) => x !== id);
}
// open a single spine as the solo rich card (collapses the multi-selection)
function openSolo(id: string) {
  multiSelected.value = [id];
  selectNode(id);
}
function clearSelection() {
  multiSelected.value = [];
  selectedNodeId.value = null;
  selectedEdgeId.value = null;
  hoverIds.value = [];
  room.clearFocus();
}
// curation: permanently delete the selected node(s) (journaled, broadcast)
async function deleteNodes() {
  const ids = selectionForHide.value;
  if (!ids.length || !confirm(t("confirmDelNodes", { n: ids.length }))) return;
  commitPeek();
  for (const id of ids) await room.actions.applyOp("delete_node", { nodeId: id });
  clearSelection();
}

// ── hide / isolate / unhide what's on the canvas ──
const hiddenIds = ref<Set<string>>(new Set());
const selectionForHide = computed(() => (multiSelected.value.length ? multiSelected.value : selectedNodeId.value ? [selectedNodeId.value] : []));
function hideSelected() {
  const next = new Set(hiddenIds.value);
  for (const id of selectionForHide.value) next.add(id);
  hiddenIds.value = next;
  multiSelected.value = [];
  selectedNodeId.value = null;
}
function isolateSelected() {
  const keep = new Set(selectionForHide.value);
  if (!keep.size) return;
  const next = new Set(hiddenIds.value);
  for (const n of room.graph.value?.graph.nodes ?? []) if (!keep.has(n.id)) next.add(n.id);
  hiddenIds.value = next;
}
function unhideAll() {
  hiddenIds.value = new Set();
}
// graph with hidden nodes removed + per-type colour overrides applied
const displayGraph = computed(() => {
  const g = room.graph.value;
  if (!g) return g;
  const hid = hiddenIds.value;
  const tc = typeColors.value;
  const recolor = Object.keys(tc).length > 0;
  if (hid.size === 0 && !recolor) return g;
  const nodes = g.graph.nodes
    .filter((n) => !hid.has(n.id))
    .map((n) => {
      const tp = n.data.tags?.[1];
      const c = tp ? tc[tp] : undefined;
      return c ? { ...n, data: { ...n.data, color: c } } : n;
    });
  const links = g.graph.links.filter((l) => !hid.has(l.source) && !hid.has(l.target));
  return { ...g, graph: { ...g.graph, nodes, links } };
});
// surface the skills tab in the sidebar when a multi-selection is active
watch(
  () => multiSelected.value.length,
  (n) => {
    if (n > 1) tab.value = "skills";
    else if (tab.value === "skills") tab.value = "suggestions";
  },
);
const selectedNames = computed(() =>
  multiSelected.value
    .map((id) => room.graph.value?.graph.nodes.find((n) => n.id === id)?.name ?? id)
    .slice(0, 4),
);
async function runOnSelection(skillId: string) {
  const ids = multiSelected.value;
  if (ids.length < 2) return;
  commitPeek();
  if (skillId === "merge") {
    // survivor = the FIRST-selected node (kept); the rest — including the
    // LAST-selected — are absorbed into it. Aliases of every absorbed node are
    // preserved on the survivor (handled in the engine's merge_nodes).
    const [survivor, ...absorbed] = ids;
    const names = ids.map((id) => room.graph.value?.graph.nodes.find((n) => n.id === id)?.name);
    await room.actions.applyOp("merge_nodes", {
      survivorId: survivor,
      absorbedIds: absorbed,
      survivorName: names[0],
      absorbedNames: names.slice(1),
    });
    multiSelected.value = [survivor!];
  } else if (skillId === "link") {
    // create a relation between the selected nodes: first = hub → the rest
    const rel = (prompt(t("relationPrompt")) ?? "").trim();
    const [hub, ...rest] = ids;
    for (const tgt of rest) {
      await room.actions.applyOp("add_edge", {
        edge: { type: "entity_relation", sourceId: hub, targetId: tgt, relation: rel || null, confidence: "extracted" },
      });
    }
    multiSelected.value = [];
  } else {
    try {
      await room.actions.runSkill(skillId, ids);
    } catch (err) {
      // destructive skills need confirmation
      if (String(err).includes("destructive") && confirm("Деструктивный скилл — применить?"))
        await room.actions.runSkill(skillId, ids, true);
    }
    multiSelected.value = [];
  }
}

function verifyFact(f: Fact, verified: boolean, nodeId?: string) {
  commitPeek();
  const ref = f.kind === "relation" ? { edgeId: f.id } : { nodeId: nodeId ?? selectedNodeId.value, attrKey: f.key };
  void room.actions.applyOp("set_verified", { ...ref, verified, asOf: room.view.asOf, axis: room.view.axis });
}
const autoRelayout = ref(localStorage.getItem("gc:autoRelayout") !== "0");
function toggleAutoRelayout() {
  autoRelayout.value = !autoRelayout.value;
  localStorage.setItem("gc:autoRelayout", autoRelayout.value ? "1" : "0");
}

// ── force-engine parameters (Layout panel sliders) ──
const showLayout = ref(false);
const layout = reactive<Record<string, number>>({
  linkDistance: 90, linkStrength: 1, chargeStrength: -320, chargeDistanceMax: 0,
  collideAdditionalRadius: 8, collideStrength: 0.1, centerStrength: 1, xStrength: 0.1, yStrength: 0.1,
});
// numeric slider spec: [key, min, max, step]
const LAYOUT_SLIDERS: [string, number, number, number][] = [
  ["linkDistance", 5, 300, 1],
  ["linkStrength", 0, 2, 0.05],
  ["chargeStrength", -600, 0, 5],
  ["chargeDistanceMax", 0, 1200, 10],
  ["collideAdditionalRadius", 0, 24, 1],
  ["collideStrength", 0, 1, 0.05],
  ["centerStrength", 0, 2, 0.05],
  ["xStrength", 0, 0.6, 0.01],
  ["yStrength", 0, 0.6, 0.01],
];
/** Seed the sliders from graph size so big graphs don't explode by default. */
function seedLayout(n: number) {
  const big = n > 250, huge = n > 700;
  layout.linkDistance = huge ? 26 : big ? 40 : 90;
  layout.chargeStrength = huge ? -36 : big ? -70 : -320;
  layout.chargeDistanceMax = big ? 180 : 0;
  layout.collideAdditionalRadius = big ? 3 : 8;
  layout.xStrength = layout.yStrength = huge ? 0.2 : big ? 0.12 : 0.1;
}
function resetLayout() {
  seedLayout(room.graph.value?.graph.nodes.length ?? 0);
}
let layoutSeeded = false;
watch(
  () => room.graph.value?.graph.nodes.length ?? 0,
  (n) => { if (!layoutSeeded && n > 0) { seedLayout(n); layoutSeeded = true; } },
  { immediate: true },
);
const showCommunities = ref(localStorage.getItem("gc:showCommunities") !== "0");
function toggleCommunities() {
  showCommunities.value = !showCommunities.value;
  localStorage.setItem("gc:showCommunities", showCommunities.value ? "1" : "0");
}

const focusIds = computed(() =>
  hoverIds.value.length ? hoverIds.value : room.focus.nodeIds,
);

function setLocale(l: string) {
  locale.value = l;
  localStorage.setItem("gc:locale", l);
}

// ── layer filter ──────────────────────────────────────────────
const layerLegend = computed(() => room.graph.value?.graph.legends?.layers ?? []);
function isLayerActive(l: string): boolean {
  return room.view.layers.length === 0 || room.view.layers.includes(l);
}
function toggleLayer(l: string) {
  const all = layerLegend.value.map((x) => x.layer);
  const cur = new Set(room.view.layers.length ? room.view.layers : all);
  if (cur.has(l)) cur.delete(l);
  else cur.add(l);
  // never empty (would hide everything) and "all selected" → [] (= all)
  const next = cur.size === 0 || cur.size === all.length ? [] : [...cur];
  void room.setView({ layers: next });
}

// ── entity-type filter (the layer panel's detail) ─────────────
const typeLegend = computed(() => room.graph.value?.graph.legends?.types ?? []);
// Kinds list: searchable + sortable (A→Z default for stability, or by count).
// Selection is by type NAME, never by position.
const kindSort = ref<"az" | "count">((localStorage.getItem("gc:kindSort") as "az" | "count") || "az");
function setKindSort(s: "az" | "count") { kindSort.value = s; localStorage.setItem("gc:kindSort", s); }
const kindQuery = ref("");
// per-type colour overrides (persisted per graph)
const tcKey = `gc:typeColors:${graphId}`;
const typeColors = ref<Record<string, string>>(JSON.parse(localStorage.getItem(tcKey) || "{}"));
function setTypeColor(type: string, color: string) {
  typeColors.value = { ...typeColors.value, [type]: color };
  localStorage.setItem(tcKey, JSON.stringify(typeColors.value));
}
const colorOf = (tp: { type: string; color: string }) => typeColors.value[tp.type] ?? tp.color;
// Entities button stat: <total>(<selected>). "selected" = nodes currently
// highlighted on the canvas — a manual selection or a RAG/agent focus set.
const totalEntities = computed(() => typeLegend.value.reduce((a, t) => a + t.count, 0));
const selectedIdSet = computed(() => new Set([...focusIds.value, ...highlightedIds.value]));
const selectedEntityCount = computed(() => selectedIdSet.value.size);
// selection broken down by entity type: { TYPE → count }
const selectedByType = computed(() => {
  const sel = selectedIdSet.value;
  const m = new Map<string, number>();
  if (!sel.size) return m;
  for (const n of room.graph.value?.graph.nodes ?? []) {
    if (!sel.has(n.id)) continue;
    const tp = n.data.tags?.[1] ?? "?";
    m.set(tp, (m.get(tp) ?? 0) + 1);
  }
  return m;
});
const kindsList = computed(() => {
  const q = kindQuery.value.trim().toLowerCase();
  const arr = typeLegend.value.filter((t) => !q || t.type.toLowerCase().includes(q));
  return [...arr].sort(kindSort.value === "count"
    ? (a, b) => b.count - a.count || a.type.localeCompare(b.type)
    : (a, b) => a.type.localeCompare(b.type));
});
// graphs can have 100+ kinds — show only the top ones inline (by count),
// the rest live in the ⚙ popover (scrollable). Active-but-not-top kinds are
// always surfaced so a filtered selection stays visible.
const KIND_INLINE = 12;
const topTypes = computed(() => {
  const sorted = [...typeLegend.value].sort((a, b) => b.count - a.count);
  const top = sorted.slice(0, KIND_INLINE);
  const shown = new Set(top.map((t) => t.type));
  const activeExtra = sorted.filter((t) => !shown.has(t.type) && room.view.types.includes(t.type));
  return [...top, ...activeExtra];
});
const moreKinds = computed(() => Math.max(0, typeLegend.value.length - topTypes.value.length));
function isTypeActive(tp: string): boolean {
  return room.view.types.length === 0 || room.view.types.includes(tp);
}
function toggleType(tp: string) {
  const all = typeLegend.value.map((x) => x.type);
  // "__none__" is the explicit "show nothing" sentinel (empty array means "all")
  const base = room.view.types.includes("__none__") ? [] : room.view.types.length ? room.view.types : all;
  const cur = new Set(base);
  if (cur.has(tp)) cur.delete(tp);
  else cur.add(tp);
  const next = cur.size === all.length ? [] : cur.size === 0 ? ["__none__"] : [...cur];
  void room.setView({ types: next });
}
function showAllKinds() { void room.setView({ types: [] }); }
function selectNoneKinds() { void room.setView({ types: ["__none__"] }); }
// ── panels toggled from the top bar (no sliding) ──
const kindsGear = ref(false);
const kindsPop = ref(false); // the unified KINDS picker popover

// ── plain node-name search (text only, no RAG) ──
const searchPop = ref(false);
const searchQuery = ref("");
const searchResults = ref<{ id: string; name: string; type: string }[]>([]);
let searchSeq = 0;
async function runSearch() {
  const q = searchQuery.value.trim();
  if (!q) { searchResults.value = []; return; }
  const mine = ++searchSeq;
  try {
    const r = await api.search(graphId, q);
    if (mine === searchSeq) searchResults.value = r;
  } catch { if (mine === searchSeq) searchResults.value = []; }
}
function pickSearch(id: string) {
  searchPop.value = false;
  hoverIds.value = [id]; // highlight + dim the rest on the canvas
  selectNode(id);
}

// ── "see what they see": adopt another participant's worldview on avatar click ──
const graphViewRef = ref<InstanceType<typeof GraphView> | null>(null);
const myActor = computed(() => room.selfActor());
// presence order: me first, then other humans, then agents
const sortedParticipants = computed(() => {
  const rank = (p: { actor: string; kind: string }) =>
    p.actor === myActor.value ? 0 : p.kind === "agent" ? 2 : 1;
  return [...room.participants.value].sort((a, b) => rank(a) - rank(b));
});
const peekActor = ref<string | null>(null);
const peekName = computed(
  () => room.participants.value.find((p) => p.actor === peekActor.value)?.name ?? peekActor.value ?? "",
);
// my own world, snapshotted the moment I start peeking so I can return to it
let myBackup: ViewSnapshot | null = null;
let applyingSnapshot = false;

function captureSnapshot(): ViewSnapshot {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const gv = graphViewRef.value as any;
  return {
    selectedNodeIds: [...highlightedIds.value],
    selectedEdgeId: selectedEdgeId.value,
    asOf: room.view.asOf,
    axis: room.view.axis,
    layers: [...room.view.layers],
    types: [...room.view.types],
    communities: showCommunities.value,
    projections: room.view.projections,
    camera: gv?.getCamera?.() ?? null,
    positions: gv?.getPositions?.() ?? {},
  };
}

async function applySnapshot(s: ViewSnapshot) {
  applyingSnapshot = true;
  // local view toggles (community hulls): keep in sync with the author
  if (s.communities !== undefined) {
    showCommunities.value = s.communities;
    localStorage.setItem("gc:showCommunities", s.communities ? "1" : "0");
  }
  // scene = filters + time + projections. AWAIT it: setView refetches the graph
  // (async), and on a big graph that completes well after a fixed timer — if we
  // applied positions before the refetch landed, the fresh data's re-layout
  // would clobber them. Wait for the new data, THEN pin the adopted layout.
  await room.setView({
    axis: s.axis ?? room.view.axis,
    asOf: s.asOf ?? null,
    layers: [...(s.layers ?? [])],
    types: [...(s.types ?? [])],
    ...(s.projections !== undefined ? { projections: s.projections } : {}),
  });
  // selection
  multiSelected.value = [...(s.selectedNodeIds ?? [])];
  selectedNodeId.value = s.selectedNodeIds?.length === 1 ? s.selectedNodeIds[0]! : null;
  selectedEdgeId.value = s.selectedEdgeId ?? null;
  // camera + exact layout, after the new data has rendered
  await nextTick();
  window.setTimeout(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (graphViewRef.value as any)?.applyView?.({ camera: s.camera, positions: s.positions });
    applyingSnapshot = false;
  }, 80);
}

function peekParticipant(actor: string) {
  if (actor === myActor.value) return; // can't peek yourself
  if (!peekActor.value) myBackup = captureSnapshot(); // remember my world the first time
  peekActor.value = actor;
  room.requestPeek(actor);
}

function returnToMyView() {
  if (myBackup) void applySnapshot(myBackup);
  myBackup = null;
  peekActor.value = null;
}

// once I start working (any edit) in an adopted view, it becomes mine — no return
function commitPeek() {
  if (!peekActor.value) return;
  myBackup = null;
  peekActor.value = null;
}

// a peer asked to see my world → reply with my current snapshot
watch(
  () => room.peekRequest.value?.seq,
  () => {
    const r = room.peekRequest.value;
    if (r) room.sendPeekState(r.from, captureSnapshot());
  },
);
// the peer's world arrived → adopt it (ignore stale replies from others)
watch(
  () => room.peekState.value?.seq,
  () => {
    const p = room.peekState.value;
    if (p && p.from === peekActor.value) void applySnapshot(p.snapshot);
  },
);

function closePops() {
  kindsPop.value = false;
  showLayout.value = false;
  searchPop.value = false;
}
function onDocClick(e: MouseEvent) {
  // click outside any top-bar popover wrapper → close the popovers
  if (!(e.target as HTMLElement)?.closest?.(".ttg-wrap")) closePops();
}
const lsBool = (k: string, d: boolean) => {
  const v = localStorage.getItem(k);
  return v == null ? d : v === "1";
};
const showKinds = ref(lsBool("gc:showKinds", false));
const showTime = ref(lsBool("gc:showTime", false));
const showSuggest = ref(lsBool("gc:showSuggest", false));
const showRag = ref(lsBool("gc:showRag", false));
function togglePanel(which: "kinds" | "time" | "suggest" | "rag") {
  const map = { kinds: showKinds, time: showTime, suggest: showSuggest, rag: showRag } as const;
  const keys = { kinds: "gc:showKinds", time: "gc:showTime", suggest: "gc:showSuggest", rag: "gc:showRag" } as const;
  const r = map[which];
  r.value = !r.value;
  localStorage.setItem(keys[which], r.value ? "1" : "0");
  // RAG and Suggestions share the right dock — only one open at a time
  if (r.value && which === "rag") { showSuggest.value = false; localStorage.setItem("gc:showSuggest", "0"); }
  if (r.value && which === "suggest") { showRag.value = false; localStorage.setItem("gc:showRag", "0"); }
}

// ── temporal axis (heatmap scrubber) ──────────────────────────
// Selecting an entity that predates the timeline highlights the genesis set.
function onSelectGenesis() {
  hoverIds.value = room.timeline.value?.genesisNodeIds ?? [];
}

function opFor(s: Record<string, unknown>): [string | null, Record<string, unknown>] {
  const a = s.action as string;
  const p = (s.payload as Record<string, unknown>) ?? {};
  if (a === "merge") return ["merge_nodes", p];
  if (a === "retype") return ["retype_node", p];
  if (a === "move") return ["move_to_community", p];
  if (a === "split") return ["split_node", p];
  if (a === "edit_relation") return ["edit_edge", p];
  if (a === "delete") return [p.edgeId ? "delete_edge" : "delete_node", p];
  return [null, p];
}

async function acceptSuggestion(s: Record<string, unknown>) {
  const [op, payload] = opFor(s);
  if (op) await room.actions.applyOp(op, payload);
  room.suggestions.value = room.suggestions.value.filter((x) => x.id !== s.id);
}
function rejectSuggestion(s: Record<string, unknown>) {
  room.suggestions.value = room.suggestions.value.filter((x) => x.id !== s.id);
}
async function compileSkill(entryIds: string[], name: string) {
  await room.actions.compileSkill({ name, entryIds, tier: "structural", scope: { kind: "graph" } });
}

const visibleNodeIds = computed(() => new Set((room.graph.value?.graph.nodes ?? []).map((n) => n.id)));
// The curation queue is a review list — show ALL pending suggestions (never hide
// by the Kinds/type filter). Ordering: suggestions touching the CURRENTLY
// SELECTED node(s) float to the top, then newest-first.
const visibleSuggestions = computed(() => {
  const sel = new Set(highlightedIds.value);
  const touchesSel = (s: Record<string, unknown>) =>
    sel.size > 0 && ((s.targetNodeIds as string[]) ?? []).some((id) => sel.has(id));
  const ts = (s: Record<string, unknown>) => String((s as { createdAt?: string }).createdAt ?? "");
  return room.suggestions.value.slice().sort((a, b) => {
    const ra = touchesSel(a) ? 1 : 0, rb = touchesSel(b) ? 1 : 0;
    if (ra !== rb) return rb - ra; // selection-relevant first
    return ts(b).localeCompare(ts(a)); // then newest
  });
});

// an agent pushed a RAG question → open the RAG console so it runs there.
watch(
  () => room.ragAsk.value?.seq,
  () => {
    if (room.ragAsk.value && !showRag.value) togglePanel("rag");
  },
);

// ── presence: broadcast what I'm looking at so the agent "sees what I see" ──
// (selection, timeline instant, active filters, the on-canvas visible slice)
let presenceTimer: number | undefined;
watch(
  () => [
    highlightedIds.value,
    selectedEdgeId.value,
    room.view.asOf,
    room.view.axis,
    room.view.layers,
    room.view.types,
    room.graph.value?.version,
    visibleNodeIds.value,
    showSuggest.value,
    showRag.value,
  ],
  () => {
    if (onHome) return;
    window.clearTimeout(presenceTimer);
    presenceTimer = window.setTimeout(() => {
      const panel = showSuggest.value ? "curation" : showRag.value ? "rag" : null;
      room.sendPresence({
        selectedNodeIds: highlightedIds.value,
        selectedEdgeId: selectedEdgeId.value,
        asOf: room.view.asOf,
        axis: room.view.axis,
        layers: [...room.view.layers],
        types: [...room.view.types],
        visibleNodeIds: [...visibleNodeIds.value],
        panel,
      });
      // server-driven assist: ping the hub when a panel is open (selection
      // optional — curation with nothing selected = graph-wide). If the hub has
      // ASSIST_CMD set it spawns a headless Claude; no-op when disabled.
      if (panel) {
        void fetch(`/api/graphs/${graphId}/assist`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ panel, nodeIds: highlightedIds.value }),
        }).catch(() => {});
      }
    }, 250);
  },
  { deep: true },
);

onMounted(async () => {
  document.addEventListener("click", onDocClick);
  if (onHome) return; // landing page — no room
  await room.refresh();
  // open with the build scenario's preferred view (axis / communities / kinds)
  const scenario = (room.graph.value as { meta?: { scenario?: { axis?: "tx" | "valid"; communities?: boolean; types?: string[] } } } | null)?.meta?.scenario;
  if (scenario) {
    if (typeof scenario.communities === "boolean") {
      showCommunities.value = scenario.communities;
      localStorage.setItem("gc:showCommunities", scenario.communities ? "1" : "0");
    }
    const patch: Partial<typeof room.view> = {};
    if (scenario.axis) patch.axis = scenario.axis;
    if (scenario.types?.length) patch.types = scenario.types;
    if (Object.keys(patch).length) await room.setView(patch);
  }
  room.connect();
  try {
    skills.value = await api.listSkills(graphId);
  } catch {
    /* none */
  }
});
</script>

<template>
  <GraphsHome v-if="onHome" @open="openGraph" />
  <div v-else class="layout">
    <header class="topbar">
      <strong class="brand-link" :title="t('graphsHeading')" @click="goHome">← {{ t("app") }}</strong>
      <span class="muted">/ {{ room.graph.value?.name ?? graphId }}</span>
      <span class="badge">{{ t("version") }}{{ room.version.value }}</span>
      <span class="dot" :class="{ on: room.connected.value }" :title="t('online')" />
      <div class="top-toggles">
        <div class="ttg-wrap">
          <button class="ttg" :class="{ on: searchPop }" :title="t('searchNode')" @click="searchPop = !searchPop">🔍</button>
          <div v-if="searchPop" class="layout-pop search-pop">
            <input
              v-model="searchQuery"
              class="kind-search"
              :placeholder="t('searchNode')"
              autofocus
              @input="runSearch"
              @keyup.enter="searchResults[0] && pickSearch(searchResults[0].id)"
            />
            <div class="search-list">
              <button v-for="r in searchResults" :key="r.id" class="search-res" @click="pickSearch(r.id)">
                <span class="gp-name">{{ r.name }}</span> <span class="muted">{{ r.type }}</span>
              </button>
              <div v-if="searchQuery.trim() && !searchResults.length" class="muted small">{{ t("noResults") }}</div>
            </div>
          </div>
        </div>
        <div class="ttg-wrap">
          <button class="ttg" :class="{ on: kindsPop || (room.view.types.length > 0) }" @click="kindsPop = !kindsPop">{{ t("kinds") }} <span class="ecount">{{ totalEntities }}<span v-if="selectedEntityCount" class="esel">({{ selectedEntityCount }})</span></span><span v-if="room.view.types.length" class="tcount"> {{ room.view.types.includes('__none__') ? 0 : room.view.types.length }}</span></button>
          <div v-if="kindsPop" class="layout-pop kinds-pop">
            <div class="lp-head">
              <strong>{{ t("kinds") }}</strong>
              <span class="gp-actions">
                <button class="link sm" :class="{ on: kindSort === 'az' }" @click="setKindSort('az')">A→Z</button>
                <button class="link sm" :class="{ on: kindSort === 'count' }" @click="setKindSort('count')"># </button>
              </span>
            </div>
            <input v-model="kindQuery" class="kind-search" :placeholder="t('searchKind')" />
            <div class="gp-actions kind-actions">
              <button class="link sm" @click="showAllKinds">{{ t("selectAll") }}</button>
              <button class="link sm" @click="selectNoneKinds">{{ t("selectNone") }}</button>
            </div>
            <div v-if="selectedEntityCount" class="sel-head">{{ t("selectedByType", { n: selectedEntityCount }) }}</div>
            <div v-for="tp in kindsList" :key="tp.type" class="gp-row" :class="{ hassel: selectedByType.get(tp.type) }">
              <input type="checkbox" :checked="isTypeActive(tp.type)" @change="toggleType(tp.type)" />
              <input type="color" class="cpick" :title="t('nodeColor')" :value="colorOf(tp)" @input="setTypeColor(tp.type, ($event.target as HTMLInputElement).value)" />
              <span class="gp-name">{{ tp.type }}</span>
              <span v-if="selectedByType.get(tp.type)" class="esel selcount">{{ selectedByType.get(tp.type) }}</span>
              <span class="muted">{{ tp.count }}</span>
            </div>
            <div v-if="!kindsList.length" class="muted small">—</div>
          </div>
        </div>
        <button class="ttg" :class="{ on: showCommunities }" :title="t('communitiesTip')" @click="toggleCommunities">◎ {{ t("communities") }}</button>
        <button class="ttg" :class="{ on: room.view.projections }" :title="t('projectionsTip')" @click="room.setView({ projections: !room.view.projections })">⨉ {{ t("projections") }}</button>
        <div class="ttg-wrap">
          <button class="ttg" :class="{ on: showLayout }" @click="showLayout = !showLayout">🧲 {{ t("layout") }}</button>
          <div v-if="showLayout" class="layout-pop">
            <div class="lp-head">
              <strong>{{ t("layout") }}</strong>
              <button class="link sm" @click="resetLayout">{{ t("reset") }}</button>
            </div>
            <label class="lp-toggle">
              <input type="checkbox" :checked="autoRelayout" @change="toggleAutoRelayout" />
              {{ t("autoLayout") }}
            </label>
            <div v-for="[k, min, max, step] in LAYOUT_SLIDERS" :key="k" class="lp-row">
              <span class="lp-name">{{ t('f_' + k) }}</span>
              <input type="range" :min="min" :max="max" :step="step" v-model.number="layout[k]" />
              <span class="lp-val">{{ layout[k] }}</span>
            </div>
          </div>
        </div>
        <button class="ttg" :class="{ on: showTime }" @click="togglePanel('time')">{{ t("timeAxis") }}</button>
        <button class="ttg" :class="{ on: showRag }" @click="togglePanel('rag')">💬 RAG</button>
        <button class="ttg" :class="{ on: showSuggest }" @click="togglePanel('suggest')">{{ t("curation") }} ({{ visibleSuggestions.length }})</button>
        <button v-if="hiddenIds.size" class="ttg" @click="unhideAll">👁 {{ t("unhideAll") }} ({{ hiddenIds.size }})</button>
      </div>
      <div class="spacer" />
      <div class="presence">
        <span
          v-for="p in sortedParticipants"
          :key="p.actor"
          class="who"
          :class="{ self: p.actor === myActor }"
        >
          <button
            class="avatar"
            :class="{ peeking: peekActor === p.actor, disabled: p.actor === myActor || p.kind === 'agent' }"
            :style="{ background: p.color }"
            :title="p.actor === myActor ? t('you') + ' — ' + p.name : p.kind === 'agent' ? p.name : t('seeWorldOf', { who: p.name })"
            :disabled="p.actor === myActor || p.kind === 'agent'"
            @click="peekParticipant(p.actor)"
          >{{ p.kind === "agent" ? "🤖" : p.name.slice(0, 1).toUpperCase() }}</button>
          <span v-if="p.actor === myActor" class="you-badge">{{ t("you") }}</span>
        </span>
      </div>
      <input v-model="actorName" class="inp sm" :placeholder="t('actor')" @change="saveActor" />
      <select class="inp sm" :value="locale" @change="setLocale(($event.target as HTMLSelectElement).value)">
        <option value="en">EN</option>
        <option value="ru">RU</option>
      </select>
    </header>

    <main class="main">
      <aside v-if="showRag" class="sidebar rag-dock rag-left">
        <div class="tabs"><button class="active">💬 RAG</button></div>
        <RagPanel :graph-id="graphId" :view="room.view" :selection="highlightedIds" :incoming-ask="room.ragAsk.value" :incoming-answer="room.ragAnswer.value" :suggested-questions="room.suggestedQuestions.value" @focus="hoverIds = $event" @select-node="selectNode" />
      </aside>
      <section class="canvas-wrap">
        <div class="graph-area">
        <div v-if="peekActor" class="peek-banner">
          👁 {{ t("viewingWorldOf", { who: peekName }) }}
          <button class="btn sm primary" :title="t('adoptWorldTip')" @click="commitPeek">⤵ {{ t("adoptWorld") }}</button>
          <button class="btn sm" @click="returnToMyView">↩ {{ t("returnToMine") }}</button>
        </div>
        <button v-if="focusIds.length && !selectionForHide.length" class="focus-clear" @click="clearSelection">✕ {{ t("clearFocus") }}</button>
        <div v-if="selectionForHide.length" class="sel-toolbar">
          <span class="muted">{{ t("selected", { n: selectionForHide.length }) }}</span>
          <button class="btn sm" @click="hideSelected">🚫 {{ t("hideSel") }}</button>
          <button class="btn sm" @click="isolateSelected">🎯 {{ t("isolate") }}</button>
          <button class="btn sm danger" @click="deleteNodes">🗑 {{ t("delNode") }}</button>
          <button class="btn sm" @click="clearSelection">✕ {{ t("clearSel") }}</button>
        </div>
        <GraphView
          ref="graphViewRef"
          :graph="displayGraph"
          :focus-ids="focusIds"
          :delta-status="room.deltaStatus.value"
          :auto-relayout="autoRelayout"
          :layout="layout"
          :freeze="room.view.asOf != null || room.view.from != null || room.view.to != null"
          :show-groups="showCommunities"
          :selected-ids="highlightedIds"
          @select-node="selectNode"
          @select-edge="selectEdge"
          @select-derived="selectDerived"
          @toggle-select="toggleSelect"
          @select-many="selectMany"
        />
        <!-- 2–4 selected nodes → one card each; closing a card deselects it -->
        <div v-if="cardIds.length" class="card-stack">
          <Inspector
            v-for="id in cardIds"
            :key="id"
            class="docked"
            :graph-id="graphId"
            :node-id="id"
            :edge-id="null"
            :derived-edge="null"
            :view="room.view"
            :config="cardConfig"
            :reload="room.version.value"
            @close="closeCard(id)"
            @select-node="(nid) => { multiSelected = []; selectNode(nid); }"
            @verify-fact="(f, v) => verifyFact(f, v, id)"
            @analyze="dossierNodeId = id"
          />
        </div>
        <!-- >4 selected → stacked spines (name + ✕); click a spine to open it solo -->
        <div v-if="spineIds.length" class="card-spines">
          <div class="spines-head">{{ t("selected", { n: multiSelected.length }) }}</div>
          <div
            v-for="id in spineIds"
            :key="id"
            class="spine"
            :title="nameOf(id)"
            @click="openSolo(id)"
          >
            <span class="spine-name">{{ nameOf(id) }}</span>
            <button class="spine-x" :title="t('clearSel')" @click.stop="closeCard(id)">✕</button>
          </div>
          <div v-if="spineOverflow" class="muted small spines-more">+{{ spineOverflow }}</div>
        </div>
        <Inspector
          v-if="!cardIds.length && !spineIds.length"
          :graph-id="graphId"
          :node-id="selectedNodeId"
          :edge-id="selectedEdgeId"
          :derived-edge="derivedSel"
          :view="room.view"
          :config="cardConfig"
          :reload="room.version.value"
          :trail="navTrail"
          @close="closeInspector"
          @select-node="selectNode"
          @nav="navTo"
          @verify-fact="verifyFact"
          @analyze="dossierNodeId = selectedNodeId"
        />
        <DossierWindow
          v-if="dossierNodeId"
          :graph-id="graphId"
          :node-id="dossierNodeId"
          :view="room.view"
          :reload="room.version.value"
          @close="dossierNodeId = null"
          @select-node="(id) => { dossierNodeId = id; selectNode(id); }"
          @op="onDossierOp"
        />
        <div v-if="room.focus.note && room.focus.by?.startsWith('agent')" class="focus-banner">
          🤖 {{ room.focus.note }}
        </div>
        </div><!-- /graph-area -->
        <div v-if="showTime && room.timeline.value" class="timelinebar">
          <span class="vb-label">{{ t("timeAxis") }}</span>
          <TimelineScrubber
            :from="room.view.from ?? null"
            :to="room.view.to ?? null"
            :events="room.timeline.value.events"
            :axis="room.view.axis"
            :bucket="room.quantBucket.value"
            :segments="room.quantSegments.value"
            :genesis-count="room.timeline.value.genesisCount"
            @update:axis="room.setView({ axis: $event })"
            @select-genesis="onSelectGenesis"
            @window="(w) => room.setView({ from: w.from, to: w.to })"
            @update:bucket="room.setQuant"
            @add-segment="room.addQuantSegment"
            @remove-segment="room.removeQuantSegment"
          />
        </div>
      </section>

      <aside v-if="showSuggest" class="sidebar">
        <div class="tabs">
          <button :class="{ active: tab === 'suggestions' }" @click="tab = 'suggestions'">
            {{ t("curation") }} ({{ visibleSuggestions.length }})
          </button>
          <button :class="{ active: tab === 'journal' }" @click="tab = 'journal'">
            {{ t("journal") }}
          </button>
          <button
            v-if="multiSelected.length > 1"
            :class="{ active: tab === 'skills' }"
            @click="tab = 'skills'"
          >
            {{ t("skills") }} ({{ multiSelected.length }})
          </button>
        </div>

        <!-- Skills for the current multi-selection (uniform cards) -->
        <SkillPanel
          v-if="tab === 'skills'"
          :count="multiSelected.length"
          :names="selectedNames"
          :node-ids="multiSelected"
          :skills="skills"
          @run="runOnSelection"
          @focus="hoverIds = $event"
          @clear="multiSelected = []"
        />

        <template v-else>
          <div class="agent-buttons">
            <button class="btn sm" @click="room.actions.runAgent('dedup')">{{ t("runDedup") }}</button>
            <button class="btn sm" :disabled="agentBusy === 'dedup-llm'" @click="runDedupLlm">{{ agentBusy === 'dedup-llm' ? '…' : t("runDedupLlm") }}</button>
            <button class="btn sm" @click="room.actions.runAgent('orphans')">{{ t("runOrphans") }}</button>
            <button class="btn sm" :disabled="agentBusy === 'skills'" @click="suggestSkills">{{ agentBusy === 'skills' ? '…' : t("suggestSkills") }}</button>
          </div>
          <SuggestionPanel
            v-if="tab === 'suggestions'"
            :suggestions="visibleSuggestions"
            @focus="hoverIds = $event"
            @accept="acceptSuggestion"
            @reject="rejectSuggestion"
          />
          <JournalPanel
            v-else
            :journal="room.journal.value"
            @revert="room.actions.revert()"
            @compile="compileSkill"
          />
        </template>
      </aside>
    </main>

    <DecisionModal :decision="room.decision.value" @resolve="room.resolveDecision" />
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
}
.topbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  background: var(--gc-panel);
  border-bottom: 1px solid var(--gc-border);
}
.spacer {
  flex: 1;
}
.brand-link {
  cursor: pointer;
}
.brand-link:hover {
  color: var(--gc-accent);
}
.badge {
  background: var(--gc-accent-soft);
  color: var(--gc-accent);
  border-radius: 5px;
  padding: 1px 6px;
  font-size: 12px;
}
.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #d33;
}
.dot.on {
  background: #34a853;
}
.presence {
  display: flex;
  gap: 6px;
  align-items: center;
}
.who { display: inline-flex; align-items: center; gap: 4px; }
.avatar {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 12px;
  color: #fff;
  border: 2px solid transparent;
  padding: 0;
  cursor: pointer;
}
.avatar:not(.disabled):hover { box-shadow: 0 0 0 2px var(--gc-accent); }
.avatar.disabled { cursor: default; }
/* my own avatar: solid dark ring so "which one is me" is obvious */
.who.self .avatar { box-shadow: 0 0 0 2px var(--gc-bg, #fff), 0 0 0 4px var(--gc-fg, #202124); opacity: 1; }
.you-badge {
  font-size: 10px;
  font-weight: 700;
  color: var(--gc-fg, #202124);
  background: var(--gc-accent-soft);
  border-radius: 8px;
  padding: 0 5px;
  text-transform: lowercase;
}
.avatar.peeking { border-color: var(--gc-accent); box-shadow: 0 0 0 2px var(--gc-accent); }
.peek-banner {
  position: absolute;
  top: 8px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 25;
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--gc-panel);
  border: 1px solid var(--gc-accent);
  border-radius: 999px;
  padding: 4px 6px 4px 14px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  font-size: 13px;
}
/* multi-select cards: a horizontal strip of node cards, scrolls if it overflows */
.card-stack {
  position: absolute;
  top: 64px;
  left: 10px;
  z-index: 6;
  display: flex;
  gap: 8px;
  max-width: calc(100% - 20px);
  overflow-x: auto;
  align-items: flex-start;
}
.card-stack :deep(.inspector) {
  position: static;
  left: auto;
  top: auto;
  flex: 0 0 auto;
  width: min(300px, 80vw);
  max-height: calc(100vh - 220px);
}
/* >4 selected: stacked spines (collapsed card headers) */
.card-spines {
  position: absolute;
  top: 64px;
  left: 10px;
  z-index: 6;
  width: 220px;
  max-height: calc(100vh - 220px);
  overflow-y: auto;
  background: var(--gc-panel);
  border: 1px solid var(--gc-border);
  border-radius: 10px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.16);
  padding: 6px;
}
.spines-head { font-size: 11px; color: var(--gc-muted, #5f6368); padding: 2px 4px 6px; }
.spine {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  border-radius: 6px;
  cursor: pointer;
  /* overlap a touch so they read like a stacked deck */
  margin-top: -1px;
  border: 1px solid var(--gc-border);
  background: var(--gc-card);
}
.spine:first-of-type { margin-top: 0; }
.spine:hover { border-color: var(--gc-accent); }
.spine-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.spine-x {
  border: none;
  background: none;
  cursor: pointer;
  color: var(--gc-muted, #80868b);
  font-size: 11px;
  padding: 0 2px;
}
.spine-x:hover { color: #c5221f; }
.spines-more { padding: 4px 6px 2px; }
.main {
  flex: 1;
  display: flex;
  min-height: 0;
}
.canvas-wrap {
  position: relative;
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.graph-area {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.viewbar {
  position: absolute;
  top: 10px;
  left: 10px;
  right: 10px;
  z-index: 5;
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  align-items: center;
  background: var(--gc-panel);
  border: 1px solid var(--gc-border);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.08);
  border-radius: 10px;
  padding: 6px 10px;
  font-size: 12px;
}
.vb-group {
  display: flex;
  align-items: center;
  gap: 6px;
}
.top-toggles {
  display: flex;
  gap: 4px;
  margin-left: 10px;
  flex-wrap: wrap;
}
.sel-toolbar {
  position: absolute; top: 10px; left: 50%; transform: translateX(-50%);
  z-index: 6; display: flex; align-items: center; gap: 8px;
  background: var(--gc-panel); border: 1px solid var(--gc-border); border-radius: 10px;
  padding: 5px 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.12); font-size: 12px;
}
.focus-clear {
  position: absolute; top: 10px; right: 12px; z-index: 6;
  border: 1px solid var(--gc-border); background: var(--gc-panel); color: var(--gc-muted, #5f6368);
  border-radius: 8px; padding: 4px 10px; cursor: pointer; font-size: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}
.focus-clear:hover { color: var(--gc-accent); border-color: var(--gc-accent); }
.sel-toolbar .btn.danger { color: #c5221f; border-color: #f3b5b2; }
.sel-toolbar .btn.danger:hover { background: #fce8e6; }
.rag-dock { display: flex; flex-direction: column; padding: 0; overflow: hidden; }
.rag-dock .tabs { padding: 6px 8px; }
.rag-left { border-left: none; border-right: 1px solid var(--gc-border); }
.ttg-wrap { position: relative; }
.layout-pop {
  position: absolute;
  top: 30px;
  left: 0;
  z-index: 20;
  background: var(--gc-panel);
  border: 1px solid var(--gc-border);
  border-radius: 8px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.18);
  padding: 10px;
  width: 260px;
}
.lp-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.lp-toggle { display: flex; align-items: center; gap: 6px; font-size: 12px; margin-bottom: 8px; }
.lp-row { display: grid; grid-template-columns: 96px 1fr 36px; align-items: center; gap: 6px; margin: 4px 0; }
.lp-name { font-size: 11px; color: var(--gc-muted, #5f6368); }
.lp-row input[type="range"] { width: 100%; }
.lp-val { font-size: 11px; text-align: right; color: var(--gc-fg); }
.ttg {
  border: 1px solid var(--gc-border);
  background: var(--gc-card);
  color: var(--gc-muted, #5f6368);
  border-radius: 7px;
  padding: 3px 10px;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
}
.ttg:hover { color: var(--gc-fg); }
.ttg.on {
  background: var(--gc-accent);
  border-color: var(--gc-accent);
  color: #fff;
}
.gp-actions { display: flex; gap: 8px; }
.kinds-pop { max-height: 60vh; overflow: auto; }
.search-pop { width: 280px; }
.search-list { max-height: 50vh; overflow: auto; display: flex; flex-direction: column; gap: 2px; margin-top: 2px; }
.search-res { display: flex; gap: 6px; align-items: baseline; text-align: left; border: none; background: none; cursor: pointer; padding: 4px 6px; border-radius: 6px; color: var(--gc-fg); font: inherit; font-size: 13px; }
.search-res:hover { background: var(--gc-accent-soft); }
.kind-search { width: 100%; box-sizing: border-box; border: 1px solid var(--gc-border); border-radius: 6px; padding: 4px 8px; margin: 4px 0; background: var(--gc-bg, #fff); color: var(--gc-fg); font: inherit; font-size: 12px; }
.kind-actions { margin-bottom: 4px; }
.cpick { width: 18px; height: 18px; padding: 0; border: 1px solid var(--gc-border); border-radius: 4px; background: none; cursor: pointer; }
.gp-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.sel-head { font-size: 11px; color: var(--gc-accent); font-weight: 600; margin: 2px 0 4px; }
.gp-row.hassel { background: var(--gc-accent-soft); border-radius: 5px; }
.selcount { font-size: 11px; font-weight: 600; color: var(--gc-accent); font-variant-numeric: tabular-nums; }
.gp-actions .link.on { color: var(--gc-accent); font-weight: 700; }
.tcount { background: rgba(255,255,255,0.25); border-radius: 8px; padding: 0 5px; margin-left: 2px; font-size: 11px; }
.ecount { font-size: 11px; opacity: 0.75; font-variant-numeric: tabular-nums; }
.esel { color: var(--gc-accent); font-weight: 600; opacity: 1; margin-left: 1px; }
.ttg.on .esel { color: #fff; }
.vb-group.kinds {
  position: relative;
}
.kinds-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  align-items: center;
  max-width: 60vw;
  max-height: 64px;
  overflow-y: auto;
}
.chip.more {
  color: var(--gc-accent);
  font-weight: 600;
}
.btn-label {
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--gc-muted, #80868b);
  font: inherit;
  text-transform: uppercase;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
}
.gear {
  border: 1px solid var(--gc-border);
  background: var(--gc-card);
  border-radius: 6px;
  cursor: pointer;
  padding: 0 5px;
  color: var(--gc-muted, #80868b);
}
.gear:hover { color: var(--gc-accent); }
.gear-pop {
  position: absolute;
  top: 28px;
  left: 0;
  z-index: 10;
  background: var(--gc-panel);
  border: 1px solid var(--gc-border);
  border-radius: 8px;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.16);
  padding: 8px;
  min-width: 200px;
  max-height: 320px;
  overflow: auto;
}
.gp-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  color: var(--gc-muted, #80868b);
  margin-bottom: 6px;
}
.gp-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 2px 0;
  cursor: pointer;
}
.link {
  border: none;
  background: transparent;
  color: var(--gc-accent);
  cursor: pointer;
}
.collapse {
  background: var(--gc-card);
  border: 1px solid var(--gc-border);
  color: var(--gc-muted, #80868b);
  border-radius: 6px;
  cursor: pointer;
  padding: 0 6px;
}
.sidebar-reopen {
  align-self: flex-start;
  margin-top: 8px;
  background: var(--gc-panel);
  border: 1px solid var(--gc-border);
  border-right: none;
  border-radius: 8px 0 0 8px;
  padding: 8px 4px;
  cursor: pointer;
  color: var(--gc-muted, #80868b);
}
.timelinebar {
  flex-shrink: 0;
  margin: 6px 10px 8px;
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--gc-panel);
  border: 1px solid var(--gc-border);
  box-shadow: 0 -2px 10px rgba(0, 0, 0, 0.06);
  border-radius: 10px;
  padding: 6px 12px;
}
.timelinebar > .vb-label {
  flex-shrink: 0;
}
.vb-label {
  color: var(--gc-muted, #80868b);
  font-weight: 600;
  text-transform: uppercase;
  font-size: 10px;
  letter-spacing: 0.04em;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid var(--gc-border);
  background: var(--gc-card);
  color: var(--gc-fg);
  border-radius: 14px;
  padding: 2px 9px;
  cursor: pointer;
}
.chip.off {
  opacity: 0.4;
}
.chip .swatch {
  width: 9px;
  height: 9px;
  border-radius: 50%;
}
.chip .muted {
  color: var(--gc-muted, #9aa0a6);
}
.focus-banner {
  position: absolute;
  top: 12px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(26, 115, 232, 0.92);
  color: #fff;
  padding: 6px 14px;
  border-radius: 18px;
  font-size: 13px;
  max-width: 70%;
}
.node-bar {
  position: absolute;
  bottom: 12px;
  left: 12px;
  display: flex;
  gap: 8px;
  align-items: center;
  background: var(--gc-panel);
  border: 1px solid var(--gc-border);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  padding: 6px 10px;
  border-radius: 8px;
  max-width: 60%;
}
.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sidebar {
  width: clamp(300px, 28vw, 420px);
  border-left: 1px solid var(--gc-border);
  background: var(--gc-panel);
  display: flex;
  flex-direction: column;
  padding: 10px;
  overflow: auto;
}
.tabs {
  display: flex;
  gap: 6px;
}
.tabs button {
  flex: 1;
  background: var(--gc-card);
  border: 1px solid var(--gc-border);
  color: var(--gc-fg);
  padding: 6px;
  border-radius: 6px;
  cursor: pointer;
}
.tabs button.active {
  background: var(--gc-accent);
  border-color: var(--gc-accent);
  color: #fff;
}
.agent-buttons {
  display: flex;
  gap: 6px;
  margin: 8px 0;
}
</style>
