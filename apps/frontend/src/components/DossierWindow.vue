<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api, type Fact, type GraphSchema, type GraphView, type NodeDetail, type SchemaField } from "@/lib/api";

const props = defineProps<{ graphId: string; nodeId: string; view: GraphView; reload?: number }>();
const emit = defineEmits<{
  (e: "close"): void;
  (e: "select-node", id: string): void;
  (e: "op", op: string, payload: Record<string, unknown>): void;
}>();
const { t } = useI18n();

const schema = ref<GraphSchema | null>(null);
const detail = ref<NodeDetail | null>(null);
const openSrc = ref<string | null>(null);
const adding = ref<string | null>(null); // section/field key being added to
const addText = ref("");

async function load() {
  try {
    if (!schema.value) schema.value = await api.getSchema(props.graphId);
    detail.value = await api.getNode(props.graphId, props.nodeId, props.view);
  } catch {
    /* gone */
  }
}
watch(() => [props.nodeId, props.view.asOf, props.view.axis, props.reload], load, { immediate: true });

const node = computed(() => detail.value?.node);
const facts = computed(() => detail.value?.facts ?? []);
// merged-in names, shown as their own chips block
const aliases = computed<string[]>(() => {
  const f = facts.value.find((x) => x.kind === "attribute" && x.key === "aliases");
  return Array.isArray(f?.value) ? (f!.value as unknown[]).map((x) => String(x)).filter(Boolean) : [];
});
const typeSchema = computed(() => schema.value?.entityTypes[node.value?.type ?? ""] ?? null);

// fact lookups
function attrFact(key: string): Fact | undefined {
  return facts.value.find((f) => f.kind === "attribute" && f.key === key);
}
function refFacts(field: SchemaField): Fact[] {
  return facts.value.filter(
    (f) => f.kind === "relation" && `${f.relation}__${f.neighbor?.type}` === field.key,
  );
}
// a schema field has content for this node?
function fieldFilled(f: SchemaField): boolean {
  return f.type === "ref" ? refFacts(f).length > 0 : !!attrFact(f.key);
}
const showEmpty = ref(false);
function fieldsOf(sec: { fields: SchemaField[] }): SchemaField[] {
  return showEmpty.value ? sec.fields : sec.fields.filter(fieldFilled);
}
const sections = computed(() => (typeSchema.value?.sections ?? []).filter((s) => showEmpty.value || fieldsOf(s).length > 0));
// schema section titles are stored in Russian (deriveSchema) → localize the
// well-known ones; fall back to whatever the schema carries.
function secTitle(sec: { key: string; title: string }): string {
  if (sec.key === "relations" || sec.title === "Связи") return t("secRelations");
  if (sec.key === "fields" || sec.key === "f" || sec.title === "Данные") return t("secData");
  return sec.title;
}

// ★ promote a field to the brief (+ in-graph card): flip its schema `summary`
// flag for this entity type and persist.
async function toggleBrief(field: SchemaField) {
  if (!schema.value || !node.value) return;
  const ts = schema.value.entityTypes[node.value.type];
  if (!ts) return;
  for (const s of ts.sections) for (const f of s.fields) if (f.key === field.key) f.summary = !f.summary;
  try {
    schema.value = await api.putSchema(props.graphId, schema.value);
  } catch {
    /* ignore */
  }
}
// facts not covered by the schema → an "Other" section
const schemaKeys = computed(() => {
  const ks = new Set<string>();
  for (const s of typeSchema.value?.sections ?? []) for (const f of s.fields) ks.add(f.key);
  return ks;
});
const otherFacts = computed(() =>
  facts.value.filter((f) =>
    f.kind === "attribute" ? !schemaKeys.value.has(f.key!) : !schemaKeys.value.has(`${f.relation}__${f.neighbor?.type}`),
  ),
);

// ── CV / interval timeline (zvezoskop-style): dated facts as bars ──
interface TLRow { id: string; from: number; to: number | null; label: string; nid: string | null; precise: boolean }
const tl = computed<TLRow[]>(() =>
  facts.value
    .filter((f) => f.validFrom)
    .map((f) => ({
      id: f.id,
      from: Date.parse(f.validFrom!),
      to: f.validTo ? Date.parse(f.validTo) : null,
      label: f.kind === "relation" ? `${f.relation}: ${f.neighbor?.name}` : `${f.key}: ${fmt(f.value)}`,
      nid: f.kind === "relation" ? f.neighbor?.id ?? null : null,
      precise: !!f.validTo,
    }))
    .filter((x) => !Number.isNaN(x.from))
    .sort((a, b) => a.from - b.from),
);
const tlMin = computed(() => Math.min(...tl.value.map((x) => x.from)));
const tlMax = computed(() => Math.max(...tl.value.map((x) => x.to ?? Date.now())));
const tlSpan = computed(() => Math.max(1, tlMax.value - tlMin.value));
function barStyle(x: TLRow) {
  const left = ((x.from - tlMin.value) / tlSpan.value) * 100;
  const end = x.to ?? tlMax.value;
  const w = Math.max(1.5, ((end - x.from) / tlSpan.value) * 100);
  return { left: `${left}%`, width: `${w}%` };
}
function tlDate(ms: number) { const d = new Date(ms); return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(); }

// ── date checks: flag implausible ranges on this node's facts + let the human
// shift the left/right boundary (applies via edit_edge) ──
interface DFix { boundary: "start" | "end"; newValue: string | null; rationale: string }
interface DFact {
  kind: "edge" | "node"; id: string; label: string;
  validFrom: string | null; validTo: string | null;
  issues: { code: string; message: string; severity: string }[];
  suggestions: DFix[];
}
const dateFacts = ref<DFact[]>([]);
const dEdit = ref<Record<string, { from: string; to: string }>>({});
const yrStr = (iso: string | null) => (iso ? String(new Date(iso).getUTCFullYear()) : "");
const yrToIso = (y: string) => (y.trim() ? `${y.trim().padStart(4, "0")}-01-01T00:00:00.000Z` : null);
async function loadDates() {
  try {
    const r = await fetch(`/api/graphs/${props.graphId}/nodes/${props.nodeId}/date-issues`).then((x) => x.json());
    dateFacts.value = (r.facts ?? []) as DFact[];
    dEdit.value = {};
    for (const f of dateFacts.value) dEdit.value[f.id] = { from: yrStr(f.validFrom), to: yrStr(f.validTo) };
  } catch {
    dateFacts.value = [];
  }
}
watch(() => [props.nodeId, props.reload], loadDates, { immediate: true });
const dateFlagCount = computed(() => dateFacts.value.filter((f) => f.issues.length).length);
function fixDate(f: DFact, fx: DFix) {
  if (f.kind !== "edge") return;
  emit("op", "edit_edge", { edgeId: f.id, updates: { [fx.boundary === "start" ? "validFrom" : "validTo"]: fx.newValue } });
}
function applyDateEdit(f: DFact) {
  if (f.kind !== "edge") return;
  const e = dEdit.value[f.id]!;
  emit("op", "edit_edge", { edgeId: f.id, updates: { validFrom: yrToIso(e.from), validTo: yrToIso(e.to) } });
}

// brief (left) = summary fields with values + first relations
const briefFields = computed(() => {
  const out: { title: string; value: string }[] = [];
  for (const s of typeSchema.value?.sections ?? [])
    for (const f of s.fields) {
      if (!f.summary) continue;
      if (f.type === "ref") {
        const names = refFacts(f).map((r) => r.neighbor?.name).filter(Boolean);
        if (names.length) out.push({ title: f.title, value: names.join(", ") });
      } else {
        const af = attrFact(f.key);
        if (af) out.push({ title: f.title, value: fmt(af.value) });
      }
    }
  return out;
});

function fmt(v: unknown): string {
  if (v == null) return "—";
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}
function pct(c: number | null | undefined): string {
  return c == null ? "" : `${Math.round(c * 100)}%`;
}
function highlight(text: string): string {
  const name = String(node.value?.name ?? "");
  const esc = (s: string) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]!));
  if (!name) return esc(text);
  return esc(text).replace(new RegExp(esc(name), "gi"), (m) => `<mark>${m}</mark>`);
}

// ── mutations (emit op → App applies + reloads) ──
function verifyAttr(key: string, on: boolean) {
  emit("op", "set_verified", { nodeId: props.nodeId, attrKey: key, verified: on, asOf: props.view.asOf, axis: props.view.axis });
}
function verifyEdge(edgeId: string, on: boolean) {
  emit("op", "set_verified", { edgeId, verified: on, asOf: props.view.asOf, axis: props.view.axis });
}
function setConfAttr(key: string) {
  const v = prompt(t("confidencePrompt"));
  if (v == null) return;
  emit("op", "set_confidence", { nodeId: props.nodeId, attrKey: key, confidence: Math.max(0, Math.min(1, Number(v) / 100)) });
}
function setConfEdge(edgeId: string) {
  const v = prompt(t("confidencePrompt"));
  if (v == null) return;
  emit("op", "set_confidence", { edgeId, confidence: Math.max(0, Math.min(1, Number(v) / 100)) });
}
function deleteAttr(key: string) {
  emit("op", "set_attribute", { nodeId: props.nodeId, key, value: null });
}
function deleteEdge(edgeId: string) {
  emit("op", "delete_edge", { edgeId });
}
function startAdd(key: string) {
  adding.value = key;
  addText.value = "";
}
function saveScalar(key: string) {
  if (addText.value.trim()) emit("op", "set_attribute", { nodeId: props.nodeId, key, value: addText.value.trim() });
  adding.value = null;
}
function toggleSrc(id: string) {
  openSrc.value = openSrc.value === id ? null : id;
}
</script>

<template>
  <div class="backdrop" @click.self="emit('close')">
    <div class="win" v-if="node">
      <!-- LEFT: brief (same projection used in the graph) -->
      <aside class="brief">
        <div class="meta muted small">
          {{ t("created") }}: {{ node.txFrom ? new Date(node.txFrom).toLocaleDateString() : "—" }}
        </div>
        <div class="name"><span class="ico">{{ typeSchema?.icon ?? "▪" }}</span> {{ node.name }}</div>
        <div class="chips">
          <span class="chip">{{ node.layer }}</span><span class="chip">{{ node.type }}</span>
          <span v-if="node.verified" class="chip ok">✓</span>
        </div>
        <p v-if="node.summary" class="summary">{{ node.summary }}</p>
        <div v-if="aliases.length" class="aliases">
          <span class="muted small">{{ t("aliases") }}:</span>
          <span v-for="a in aliases" :key="a" class="alias-chip">{{ a }}</span>
        </div>
        <dl class="brief-fields">
          <template v-for="b in briefFields" :key="b.title">
            <dt>{{ b.title }}</dt><dd>{{ b.value }}</dd>
          </template>
        </dl>
        <div class="badges">
          <span class="b">{{ t("facts") }}: {{ facts.length }}</span>
          <button v-if="detail?.sources.length" class="b mlink" @click="openSrc = openSrc === '__node__' ? null : '__node__'">
            📄 {{ t("mentionedInN", { n: detail.sources.length }) }}
          </button>
        </div>
        <div v-if="openSrc === '__node__' && detail?.sources.length" class="src nodesrc">
          <details v-for="(s, i) in detail.sources" :key="s.id" class="src-d" :open="detail.sources.length === 1">
            <summary>{{ s.documentId || t("chunk") }} #{{ i + 1 }}</summary>
            <!-- eslint-disable-next-line vue/no-v-html -->
            <div class="src-text" v-html="highlight(String(s.text ?? ''))" />
          </details>
        </div>
      </aside>

      <!-- RIGHT: working area (schema sections) -->
      <section class="work">
        <div class="whead">
          <strong>{{ t("workspace") }}</strong>
          <label class="empty-tg"><input type="checkbox" v-model="showEmpty" /> {{ t("showEmptyFields") }}</label>
          <div class="sp" />
          <button class="x" @click="emit('close')">✕</button>
        </div>

        <!-- CV / interval timeline (zvezoskop-style) -->
        <div v-if="tl.length" class="sec cv">
          <div class="sec-h">⏱ {{ t("cvTimeline") }} <span class="muted small">{{ tlDate(tlMin) }} — {{ tlDate(tlMax) }}</span></div>
          <div v-for="x in tl" :key="x.id" class="cv-row">
            <span class="cv-label" :class="{ link: x.nid }" @click="x.nid && emit('select-node', x.nid)">{{ x.label }}</span>
            <span class="cv-track">
              <span class="cv-bar" :class="{ open: !x.precise }" :style="barStyle(x)" :title="`${tlDate(x.from)}${x.to ? ' — ' + tlDate(x.to) : ' →'}`" />
            </span>
            <span class="cv-when muted small">{{ tlDate(x.from) }}{{ x.to ? "–" + tlDate(x.to) : "→" }}</span>
          </div>
          <div class="cv-legend muted small">▮ {{ t("cvExact") }} · ▭ {{ t("cvOpen") }}</div>
        </div>

        <!-- date checks: shift the left/right boundary of any dated fact; flag
             implausible ranges (e.g. a role since 1933 still open today) -->
        <div v-if="dateFacts.length" class="sec">
          <div class="sec-h">📅 Date checks
            <span v-if="dateFlagCount" class="dwarn">{{ dateFlagCount }} to fix</span>
          </div>
          <div v-for="f in dateFacts" :key="f.id" class="dfact" :class="{ bad: f.issues.length }">
            <div class="f-label">{{ f.label }}<span v-if="f.kind === 'node'" class="muted small"> · read-only</span></div>
            <div v-for="(i, k) in f.issues" :key="k" class="dissue">⚠ {{ i.message }}</div>
            <div class="row">
              <input v-model="dEdit[f.id]!.from" class="inp dyr" :disabled="f.kind !== 'edge'" placeholder="—" />
              <span class="muted">→</span>
              <input v-model="dEdit[f.id]!.to" class="inp dyr" :disabled="f.kind !== 'edge'" placeholder="present" />
              <button v-if="f.kind === 'edge'" class="mini on" @click="applyDateEdit(f)">Apply</button>
            </div>
            <div v-if="f.suggestions.length && f.kind === 'edge'" class="dfixes">
              <button v-for="(s, k) in f.suggestions" :key="k" class="addbtn" :title="s.rationale" @click="fixDate(f, s)">
                {{ s.boundary === "start" ? "◀ start" : "end ▶" }}: {{ s.rationale }}
              </button>
            </div>
          </div>
        </div>

        <div v-for="sec in sections" :key="sec.key" class="sec">
          <div class="sec-h">{{ secTitle(sec) }}</div>
          <div v-for="f in fieldsOf(sec)" :key="f.key" class="field">
            <!-- REF field: linked entities -->
            <template v-if="f.type === 'ref'">
              <div class="f-label">{{ f.icon }} {{ f.title }}
                <button class="mini star" :class="{ on: f.summary }" :title="t('toCard')" @click="toggleBrief(f)">★</button>
              </div>
              <div v-for="rf in refFacts(f)" :key="rf.id" class="row">
                <span class="val link" @click="rf.neighbor && emit('select-node', rf.neighbor.id)">{{ rf.neighbor?.name }}</span>
                <span class="conf">{{ pct(rf.confidence) }}</span>
                <button v-if="rf.sourceCount" class="mini" @click="toggleSrc(rf.id)">[{{ rf.sourceCount }}]</button>
                <button v-if="!rf.verified" class="mini" :title="t('verify')" @click="verifyEdge(rf.id, true)">✓</button>
                <template v-else>
                  <button class="mini" :class="rf.stale ? 'stale' : 'on'" :title="rf.stale ? t('staleTip') : ''" @click="verifyEdge(rf.id, true)">{{ rf.stale ? "⚠" : "✓" }}</button>
                  <button class="mini x" :title="t('unverify')" @click="verifyEdge(rf.id, false)">✕</button>
                </template>
                <button class="mini" @click="setConfEdge(rf.id)">%</button>
                <button class="mini del" @click="deleteEdge(rf.id)">🗑</button>
                <div v-if="openSrc === rf.id" class="src">
                  <!-- eslint-disable-next-line vue/no-v-html -->
                  <div v-for="s in rf.sources" :key="s.id" class="src-text" v-html="highlight(String(s.text ?? ''))" />
                  <div v-if="!rf.sources.length" class="muted small">{{ t("noSourceText") }}</div>
                </div>
              </div>
            </template>
            <!-- SCALAR field -->
            <template v-else>
              <div class="row">
                <span class="f-label">{{ f.icon }} {{ f.title }}
                  <button class="mini star" :class="{ on: f.summary }" :title="t('toCard')" @click="toggleBrief(f)">★</button>
                </span>
                <template v-if="attrFact(f.key)">
                  <span class="val">{{ fmt(attrFact(f.key)!.value) }}</span>
                  <span class="conf">{{ pct(attrFact(f.key)!.confidence) }}</span>
                  <button v-if="attrFact(f.key)!.sourceCount" class="mini" @click="toggleSrc(f.key)">[{{ attrFact(f.key)!.sourceCount }}]</button>
                  <button v-if="!attrFact(f.key)!.verified" class="mini" :title="t('verify')" @click="verifyAttr(f.key, true)">✓</button>
                  <template v-else>
                    <button class="mini" :class="attrFact(f.key)!.stale ? 'stale' : 'on'" :title="attrFact(f.key)!.stale ? t('staleTip') : ''" @click="verifyAttr(f.key, true)">{{ attrFact(f.key)!.stale ? "⚠" : "✓" }}</button>
                    <button class="mini x" :title="t('unverify')" @click="verifyAttr(f.key, false)">✕</button>
                  </template>
                  <button class="mini" @click="setConfAttr(f.key)">%</button>
                  <button class="mini del" @click="deleteAttr(f.key)">🗑</button>
                </template>
                <template v-else-if="adding === f.key">
                  <input v-model="addText" class="inp" @keyup.enter="saveScalar(f.key)" />
                  <button class="mini" @click="saveScalar(f.key)">OK</button>
                </template>
                <button v-else class="addbtn" @click="startAdd(f.key)">＋</button>
              </div>
              <div v-if="openSrc === f.key && attrFact(f.key)" class="src">
                <!-- eslint-disable-next-line vue/no-v-html -->
                <div v-for="s in attrFact(f.key)!.sources" :key="s.id" class="src-text" v-html="highlight(String(s.text ?? ''))" />
                <div v-if="!attrFact(f.key)!.sources.length" class="muted small">{{ t("noSourceText") }}</div>
              </div>
            </template>
          </div>
        </div>

        <div v-if="otherFacts.length" class="sec">
          <div class="sec-h">{{ t("other") }}</div>
          <div v-for="f in otherFacts" :key="f.id" class="row">
            <span class="f-label">{{ f.kind === "relation" ? `${f.relation} →` : f.key }}</span>
            <span class="val" :class="{ link: f.kind === 'relation' }" @click="f.kind === 'relation' && f.neighbor ? emit('select-node', f.neighbor.id) : null">{{ f.kind === "relation" ? f.neighbor?.name : fmt(f.value) }}</span>
            <span class="conf">{{ pct(f.confidence) }}</span>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 3000; }
.win { display: grid; grid-template-columns: 280px 1fr; gap: 0; background: var(--gc-panel); color: var(--gc-fg); width: min(960px, 96vw); height: 86vh; border-radius: 12px; overflow: hidden; box-shadow: 0 12px 40px rgba(0,0,0,0.4); }
.brief { border-right: 1px solid var(--gc-border); padding: 14px; overflow: auto; background: var(--gc-card); }
.empty-tg { font-size: 11px; color: var(--gc-muted, #80868b); display: flex; align-items: center; gap: 4px; margin-left: 12px; }
.sp { flex: 1; }
.star { color: var(--gc-muted, #c0c4c9); }
.star.on { color: #f9ab00; }
.cv-row { display: grid; grid-template-columns: 160px 1fr 92px; align-items: center; gap: 8px; margin: 3px 0; font-size: 12px; }
.cv-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cv-label.link { color: var(--gc-accent); cursor: pointer; }
.cv-track { position: relative; height: 12px; background: var(--gc-card); border-radius: 6px; }
.cv-bar { position: absolute; top: 1px; bottom: 1px; background: var(--gc-accent); border-radius: 5px; min-width: 4px; }
.cv-bar.open { background: linear-gradient(90deg, var(--gc-accent), rgba(26,115,232,0.15)); }
.cv-when { text-align: right; font-variant-numeric: tabular-nums; }
.cv-legend { margin-top: 6px; }
.name { font-size: 17px; font-weight: 600; margin: 4px 0; }
.ico { margin-right: 4px; }
.chips { display: flex; gap: 4px; margin: 6px 0; }
.chip { border: 1px solid var(--gc-border); border-radius: 12px; padding: 0 8px; font-size: 11px; }
.chip.ok { background: #e6f4ea; border-color: #1e8e3e; color: #1e8e3e; }
.summary { font-size: 13px; margin: 8px 0; }
.brief-fields { display: grid; grid-template-columns: auto 1fr; gap: 2px 10px; font-size: 13px; margin: 8px 0; }
.brief-fields dt { color: var(--gc-muted, #80868b); text-transform: uppercase; font-size: 10px; align-self: center; }
.brief-fields dd { margin: 0; }
.aliases { margin: 8px 0 2px; display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.alias-chip { border: 1px solid var(--gc-border); border-radius: 10px; padding: 1px 8px; font-size: 11px; background: var(--gc-accent-soft); color: var(--gc-accent); }
.badges { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; } .b { border: 1px solid var(--gc-border); border-radius: 10px; padding: 1px 8px; font-size: 11px; }
.b.mlink { cursor: pointer; color: var(--gc-accent); background: transparent; }
.nodesrc { margin-top: 8px; }
.src-d > summary { cursor: pointer; font-size: 12px; color: var(--gc-accent); }
.work { padding: 14px; overflow: auto; }
.whead { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.x { border: none; background: transparent; cursor: pointer; font-size: 16px; color: var(--gc-muted, #80868b); }
.sec { border: 1px solid var(--gc-border); border-radius: 8px; padding: 8px 10px; margin-bottom: 10px; }
.sec-h { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--gc-muted, #80868b); font-weight: 600; margin-bottom: 6px; }
.field { padding: 3px 0; }
.f-label { color: var(--gc-muted, #5f6368); font-size: 12px; min-width: 120px; }
.row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; padding: 2px 0; }
.val { font-weight: 500; overflow-wrap: anywhere; }
.val.link { color: var(--gc-accent); cursor: pointer; }
.conf { font-size: 11px; color: var(--gc-muted, #80868b); }
.mini { border: 1px solid var(--gc-border); background: var(--gc-card); border-radius: 5px; padding: 0 6px; font-size: 11px; cursor: pointer; color: var(--gc-muted, #80868b); }
.mini.on { background: #e6f4ea; border-color: #1e8e3e; color: #1e8e3e; }
.mini.stale { background: #fef7e0; border-color: #f9ab00; color: #b06000; }
.mini.x { color: #c5221f; }
.mini.del:hover { color: #c5221f; }
.addbtn { border: 1px dashed var(--gc-border); background: transparent; border-radius: 5px; padding: 0 8px; cursor: pointer; color: var(--gc-accent); font-size: 12px; }
.add { display: flex; flex-direction: column; gap: 3px; margin: 4px 0; }
.res { text-align: left; border: 1px solid var(--gc-border); background: var(--gc-card); border-radius: 5px; padding: 2px 6px; cursor: pointer; font-size: 12px; }
.inp { border: 1px solid var(--gc-border); border-radius: 5px; padding: 2px 6px; background: var(--gc-bg, #fff); color: var(--gc-fg); }
.src { width: 100%; }
.src-text { font-size: 12px; line-height: 1.5; background: var(--gc-card); border: 1px solid var(--gc-border); border-radius: 6px; padding: 8px; white-space: pre-wrap; max-height: 160px; overflow: auto; margin: 4px 0; }
.src-text :deep(mark) { background: #fff176; }
.muted { color: var(--gc-muted, #80868b); } .small { font-size: 11px; }
.dwarn { font-size: 10px; background: #fce8e6; color: #c5221f; border-radius: 8px; padding: 1px 6px; margin-left: 6px; font-weight: 600; }
.dfact { padding: 5px 0; border-top: 1px dashed var(--gc-border); }
.dfact:first-of-type { border-top: none; }
.dfact.bad .f-label { color: #c5221f; }
.dissue { font-size: 11px; color: #b06000; margin: 2px 0; }
.dyr { width: 58px; }
.dfixes { display: flex; flex-direction: column; gap: 3px; margin-top: 4px; }
</style>
