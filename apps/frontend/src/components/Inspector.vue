<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api, type EdgeDetail, type Fact, type GraphView, type NodeDetail } from "@/lib/api";

export interface CardConfig {
  minConfidence: number;
  verifiedOnly: boolean;
  showRelations: boolean;
  showAttributes: boolean;
}

type Projection = Awaited<ReturnType<typeof api.projectionEdge>>;

const props = defineProps<{
  graphId: string;
  nodeId: string | null;
  edgeId: string | null;
  derivedEdge?: { source: string; target: string; relation: string } | null;
  view: GraphView;
  config: CardConfig;
  /** Bump to force a reload after a fact edit (room version). */
  reload?: number;
  /** drill-down breadcrumb trail (entity → entity). */
  trail?: { id: string; name: string }[];
}>();
const emit = defineEmits<{
  (e: "close"): void;
  (e: "select-node", id: string): void;
  (e: "nav", i: number): void;
  (e: "verify-fact", fact: Fact, verified: boolean): void;
  (e: "analyze"): void;
}>();
const { t } = useI18n();

const detail = ref<NodeDetail | null>(null);
const edge = ref<EdgeDetail | null>(null);
const projection = ref<Projection | null>(null);
const openFact = ref<string | null>(null);
const openSrc = ref<string | null>(null);
const openMentions = ref(false); // node-level "mentioned in" provenance

async function load() {
  detail.value = null;
  edge.value = null;
  projection.value = null;
  openFact.value = null;
  openSrc.value = null;
  openMentions.value = false;
  try {
    if (props.nodeId) detail.value = await api.getNode(props.graphId, props.nodeId, props.view);
    else if (props.edgeId) edge.value = await api.getEdge(props.graphId, props.edgeId);
    else if (props.derivedEdge) projection.value = await api.projectionEdge(props.graphId, props.derivedEdge.source, props.derivedEdge.target, props.derivedEdge.relation);
  } catch {
    /* gone */
  }
}
watch(() => [props.nodeId, props.edgeId, props.derivedEdge, props.view.asOf, props.view.axis, props.reload], load, { immediate: true, deep: true });

// internal/stat attributes that aren't real "facts" ("aliases" gets its own chip block)
const NOISE_KEYS = new Set(["mentionCount", "size", "algorithm", "charStart", "charEnd", "length", "rawWeight", "mentions", "aliases"]);

// merged-in names, shown as their own chips block
const aliases = computed<string[]>(() => {
  const f = detail.value?.facts.find((x) => x.kind === "attribute" && x.key === "aliases");
  return Array.isArray(f?.value) ? (f!.value as unknown[]).map((x) => String(x)).filter(Boolean) : [];
});
function isEmptyFact(f: Fact): boolean {
  if (f.kind === "relation") return !f.neighbor?.name; // dangling relation
  if (NOISE_KEYS.has(f.key ?? "")) return true;
  const v = f.value;
  if (v == null || v === "" || v === "—") return true;
  if (Array.isArray(v)) return v.length === 0;
  if (typeof v === "object") return Object.keys(v as object).length === 0;
  return false;
}

// Card filter: drop empty/noise facts; then show verified OR (confidence ≥
// threshold) OR confidence-unknown (extracted facts carry no numeric score).
const shown = computed<Fact[]>(() => {
  const c = props.config;
  const facts = (detail.value?.facts ?? [])
    .filter((f) => (f.kind === "relation" ? c.showRelations : c.showAttributes))
    .filter((f) => !isEmptyFact(f));
  const pass = facts.filter((f) =>
    c.verifiedOnly ? !!f.verified : !!f.verified || f.confidence == null || f.confidence >= c.minConfidence,
  );
  return pass.sort((a, b) => {
    if (!!b.verified !== !!a.verified) return (b.verified ? 1 : 0) - (a.verified ? 1 : 0);
    return (b.confidence ?? -1) - (a.confidence ?? -1);
  });
});
const hiddenCount = computed(() => (detail.value?.facts.filter((f) => !isEmptyFact(f)).length ?? 0) - shown.value.length);

function factText(f: Fact): string {
  if (f.kind === "relation") return `${f.dir === "out" ? "→" : "←"} ${f.relation}: ${f.neighbor?.name}`;
  return `${f.key}: ${fmt(f.value)}`;
}
function fmt(v: unknown): string {
  if (v == null) return "—";
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}
function pct(c: number | null): string {
  return c == null ? "—" : `${Math.round(c * 100)}%`;
}
function verifiedTip(f: Fact): string {
  const v = f.verified;
  if (!v) return "";
  const d = new Date(v.at);
  const when = Number.isNaN(d.getTime()) ? v.at : d.toLocaleString();
  const asof = v.asOf ? new Date(v.asOf).toLocaleDateString() : t("live");
  return `${t("verifiedBy", { who: v.by })} · ${when} · ${t("asOf")} ${asof}`;
}
function toggleFact(f: Fact) {
  openFact.value = openFact.value === f.id ? null : f.id;
}
function highlight(text: string): string {
  const name = String(detail.value?.node.name ?? "");
  const esc = (s: string) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]!));
  const safe = esc(text);
  if (!name) return safe;
  try {
    // escape regex metachars in the entity name (C++, Node.js, (x) … would throw)
    const rx = esc(name).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return safe.replace(new RegExp(rx, "gi"), (m) => `<mark>${m}</mark>`);
  } catch {
    return safe;
  }
}
const e = computed(() => (edge.value?.edge ?? {}) as Record<string, any>);
const projVia = computed(() => (projection.value?.relation === "co_community" ? t("communities") : t("chunks")));
</script>

<template>
  <div v-if="nodeId || edgeId || derivedEdge" class="inspector">
    <!-- breadcrumbs: drill trail across cards -->
    <div v-if="(trail?.length ?? 0) > 1" class="crumbs">
      <button class="crumb-back" :title="t('back')" @click="emit('nav', (trail?.length ?? 1) - 2)">←</button>
      <template v-for="(c, i) in trail" :key="c.id">
        <span v-if="i" class="sep">›</span>
        <button class="crumb" :class="{ cur: i === (trail?.length ?? 0) - 1 }" @click="emit('nav', i)">{{ c.name }}</button>
      </template>
    </div>
    <!-- NODE CARD -->
    <template v-if="detail">
      <div class="head">
        <strong class="title">{{ detail.node.name }}</strong>
        <div class="hd-btns">
          <button class="x" :title="t('analysis')" @click="emit('analyze')">⤢</button>
          <button class="x" @click="emit('close')">✕</button>
        </div>
      </div>
      <div class="chips">
        <span class="chip">{{ detail.node.layer }}</span>
        <span class="chip">{{ detail.node.type }}</span>
      </div>
      <p v-if="detail.node.summary" class="summary">{{ detail.node.summary }}</p>

      <!-- aliases (merged-in names) -->
      <div v-if="aliases.length" class="aliases">
        <span class="muted small">{{ t("aliases") }}:</span>
        <span v-for="a in aliases" :key="a" class="alias-chip">{{ a }}</span>
      </div>

      <!-- node-level provenance: where this entity is mentioned in the corpus -->
      <div v-if="detail.sources.length" class="mentions">
        <button class="badge mlink" @click="openMentions = !openMentions">
          📄 {{ t("mentionedInN", { n: detail.sources.length }) }} {{ openMentions ? "▾" : "▸" }}
        </button>
        <div v-if="openMentions" class="src">
          <details v-for="(s, i) in detail.sources" :key="s.id" class="src-item" :open="detail.sources.length === 1">
            <summary>{{ s.documentId || t("chunk") }} #{{ i + 1 }}</summary>
            <!-- eslint-disable-next-line vue/no-v-html -->
            <div class="src-text" v-html="highlight(String(s.text ?? ''))" />
          </details>
        </div>
      </div>

      <h4>{{ t("facts") }} <span class="muted">({{ shown.length }})</span></h4>
      <ul v-if="shown.length" class="facts">
        <li v-for="f in shown" :key="f.id" class="fact">
          <div class="fact-row">
            <span
              class="ftext"
              :class="{ link: f.kind === 'relation' }"
              @click="f.kind === 'relation' && f.neighbor ? emit('select-node', f.neighbor.id) : null"
            >{{ factText(f) }}</span>
            <span class="conf" :class="{ hi: (f.confidence ?? 0) >= 0.9 }">{{ pct(f.confidence) }}</span>
            <button
              v-if="f.sourceCount"
              class="badge"
              :title="t('sourcesN', { n: f.sourceCount })"
              @click="toggleFact(f)"
            >[{{ f.sourceCount }}]</button>
            <template v-if="!f.verified">
              <button class="vbtn" :title="t('verify')" @click="emit('verify-fact', f, true)">✓</button>
            </template>
            <template v-else>
              <button
                class="vbtn"
                :class="f.stale ? 'stale' : 'on'"
                :title="f.stale ? t('staleTip') : verifiedTip(f)"
                @click="emit('verify-fact', f, true)"
              >{{ f.stale ? "⚠" : "✓" }}</button>
              <button class="vbtn x" :title="t('unverify')" @click="emit('verify-fact', f, false)">✕</button>
            </template>
          </div>
          <!-- 1 source → open directly; N → list, each opens -->
          <div v-if="openFact === f.id" class="src-wrap">
            <template v-if="f.sources.length === 1">
              <!-- eslint-disable-next-line vue/no-v-html -->
              <div class="src-text" v-html="highlight(String(f.sources[0]?.text ?? ''))" />
            </template>
            <template v-else>
              <details v-for="(s, i) in f.sources" :key="s.id" class="src-item">
                <summary>📄 {{ s.documentId || `#${i + 1}` }}</summary>
                <!-- eslint-disable-next-line vue/no-v-html -->
                <div class="src-text" v-html="highlight(String(s.text ?? ''))" />
              </details>
              <div v-if="!f.sources.length" class="muted small">{{ t("noSourceText") }}</div>
            </template>
          </div>
        </li>
      </ul>
      <p v-else class="muted small">{{ t("noFactsShown") }}</p>
      <button v-if="hiddenCount > 0" class="more" @click="emit('analyze')">
        +{{ hiddenCount }} {{ t("hiddenFacts") }} → {{ t("analysis") }}
      </button>
    </template>

    <!-- EDGE CARD (direct edge click) -->
    <template v-else-if="edge">
      <div class="head">
        <strong class="title">{{ edge.source.name }} → {{ edge.target.name }}</strong>
        <button class="x" @click="emit('close')">✕</button>
      </div>
      <div class="chips">
        <span class="chip">{{ e.type }}</span>
        <span v-if="e.relation" class="chip">{{ e.relation }}</span>
        <span class="chip muted">{{ e.confidence }}</span>
      </div>
      <table>
        <tr><td class="k">{{ t("from") }}</td><td class="v link" @click="emit('select-node', edge.source.id)">{{ edge.source.name }}</td></tr>
        <tr><td class="k">{{ t("to") }}</td><td class="v link" @click="emit('select-node', edge.target.id)">{{ edge.target.name }}</td></tr>
        <tr v-if="e.explanation"><td class="k">{{ t("explanation") }}</td><td class="v">{{ e.explanation }}</td></tr>
      </table>
    </template>

    <!-- DERIVED (Batagelj projection) edge: what it's composed of -->
    <template v-else-if="projection">
      <div class="head">
        <strong class="title">
          <span class="link" @click="emit('select-node', projection.source.id)">{{ projection.source.name }}</span>
          ⨉
          <span class="link" @click="emit('select-node', projection.target.id)">{{ projection.target.name }}</span>
        </strong>
        <button class="x" @click="emit('close')">✕</button>
      </div>
      <div class="chips">
        <span class="chip" :style="{ borderColor: '#a142f4', color: '#a142f4' }">{{ projection.relation }}</span>
        <span class="chip muted">{{ t("projDerived") }}</span>
      </div>
      <p class="summary small">{{ t("projExplain", { n: projection.raw, w: projection.weight.toFixed(2), via: projVia }) }}</p>
      <h4>{{ t("projShared") }} <span class="muted">({{ projection.raw }})</span></h4>
      <ul class="facts">
        <li v-for="m in projection.intermediaries" :key="m.id" class="fact">
          <div class="fact-row">
            <span class="ftext" :class="{ link: !!m.text }" @click="m.text ? (openSrc = openSrc === m.id ? null : m.id) : null">
              {{ m.kind === "community" ? "◎" : "📄" }} {{ m.documentId || m.name }}
            </span>
            <span class="conf" :title="t('projDegree', { d: m.degree })">×{{ m.contribution.toFixed(2) }}</span>
          </div>
          <div v-if="openSrc === m.id && m.text" class="src-wrap">
            <div class="src-text">{{ m.text }}</div>
          </div>
        </li>
      </ul>
    </template>
  </div>
</template>

<style scoped>
.inspector {
  position: absolute; top: 64px; left: 10px; z-index: 6;
  width: min(360px, 42vw); max-height: calc(100% - 150px); overflow: auto;
  background: var(--gc-panel); border: 1px solid var(--gc-border);
  border-radius: 10px; box-shadow: 0 6px 24px rgba(0, 0, 0, 0.16); padding: 12px; font-size: 13px;
}
.crumbs { display: flex; align-items: center; flex-wrap: wrap; gap: 2px; margin-bottom: 6px; font-size: 11px; }
.crumb-back { border: 1px solid var(--gc-border); background: var(--gc-card); border-radius: 6px; cursor: pointer; padding: 0 6px; margin-right: 4px; color: var(--gc-fg); }
.crumb { border: none; background: none; cursor: pointer; color: var(--gc-accent); padding: 0 2px; max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.crumb.cur { color: var(--gc-fg); font-weight: 600; cursor: default; }
.sep { color: var(--gc-muted, #9aa0a6); }
.head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.hd-btns { display: flex; gap: 4px; }
.title { font-size: 15px; overflow-wrap: anywhere; }
.x { border: none; background: transparent; color: var(--gc-muted, #80868b); cursor: pointer; font-size: 15px; }
.x:hover { color: var(--gc-fg); }
.chips { display: flex; flex-wrap: wrap; gap: 5px; margin: 8px 0; }
.chip { border: 1px solid var(--gc-border); border-radius: 12px; padding: 1px 8px; font-size: 11px; }
.chip.muted { color: var(--gc-muted, #80868b); }
.summary { margin: 8px 0; }
h4 { margin: 12px 0 4px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--gc-muted, #80868b); }
.facts { list-style: none; margin: 0; padding: 0; }
.fact { border-top: 1px solid var(--gc-border); padding: 5px 0; }
.fact-row { display: flex; align-items: center; gap: 6px; }
.ftext { flex: 1; overflow-wrap: anywhere; }
.ftext.link { color: var(--gc-accent); cursor: pointer; }
.conf { font-size: 11px; color: var(--gc-muted, #80868b); min-width: 34px; text-align: right; }
.conf.hi { color: #1e8e3e; font-weight: 600; }
.badge { border: 1px solid var(--gc-border); background: var(--gc-card); border-radius: 5px; padding: 0 5px; font-size: 11px; cursor: pointer; color: var(--gc-accent); }
.vbtn { border: 1px solid var(--gc-border); background: var(--gc-card); border-radius: 5px; width: 22px; cursor: pointer; color: var(--gc-muted, #b0b4bb); }
.vbtn.on { background: #e6f4ea; border-color: #1e8e3e; color: #1e8e3e; }
.vbtn.stale { background: #fef7e0; border-color: #f9ab00; color: #b06000; }
.vbtn.x { color: #c5221f; }
.vbtn.x:hover { background: #fce8e6; border-color: #c5221f; }
.aliases { margin: 6px 0 2px; display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.alias-chip { border: 1px solid var(--gc-border); border-radius: 10px; padding: 1px 8px; font-size: 11px; background: var(--gc-accent-soft); color: var(--gc-accent); }
.mentions { margin: 6px 0 2px; }
.mlink { font-size: 12px; }
.src { margin-top: 4px; display: flex; flex-direction: column; gap: 4px; }
.src-wrap { margin: 4px 0 2px; }
.src-item > summary { cursor: pointer; font-size: 12px; color: var(--gc-accent); }
.src-text { font-size: 12px; line-height: 1.5; background: var(--gc-card); border-radius: 6px; padding: 8px; white-space: pre-wrap; max-height: 160px; overflow: auto; margin-top: 4px; }
.src-text :deep(mark) { background: #fff176; padding: 0 1px; }
.more { margin-top: 8px; background: none; border: none; color: var(--gc-accent); cursor: pointer; font-size: 12px; padding: 0; }
table { width: 100%; border-collapse: collapse; }
td { padding: 2px 4px; vertical-align: top; }
td.k { color: var(--gc-muted, #80868b); white-space: nowrap; width: 30%; }
.v.link, .link { color: var(--gc-accent); cursor: pointer; }
.muted { color: var(--gc-muted, #80868b); }
.small { font-size: 12px; }
</style>
