<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { api, type GraphScenario, type RankedScenario, type SetupSession, type WhyReason } from "@/lib/api";

// projectId null = new project: the first turn collects the source and creates
// the project, then the same conversation continues into analysis + scenarios.
const props = defineProps<{ projectId: string | null; projectName: string }>();
const emit = defineEmits<{ (e: "close"): void; (e: "built", id: string): void }>();
const { t, te } = useI18n();

// scenario display strings live in i18n (keyed by id) so cards follow the
// active locale; fall back to whatever the server catalog carries.
const scKey = (id: string, part: string) => `sc_${id.replace(/-/g, "_")}_${part}`;
const scTitle = (s: GraphScenario) => (te(scKey(s.id, "title")) ? t(scKey(s.id, "title")) : s.title);
const scSub = (s: GraphScenario) => (te(scKey(s.id, "sub")) ? t(scKey(s.id, "sub")) : s.subtitle);
const scCat = (s: GraphScenario) => (te(scKey(s.id, "cat")) ? t(scKey(s.id, "cat")) : s.category);
const scAns = (s: GraphScenario) => (te(scKey(s.id, "ans")) ? t(scKey(s.id, "ans")).split("|") : s.answers);
const WHY: Record<WhyReason["code"], string> = { types: "whyTypes", time: "whyTime", chat: "whyChat", goal: "whyGoal", terms: "whyTerms" };
const whyText = (w: WhyReason) => t(WHY[w.code], { arg: w.arg ?? "" });
const goalChips = computed(() => t("goalSuggests").split("|"));

const pid = ref<string | null>(props.projectId ?? null);
const projName = ref(props.projectName ?? "");

const session = ref<SetupSession | null>(null);
const revealed = ref(1); // how many steps are in the transcript (1..7)
const goalDraft = ref("");
const graphNameDraft = ref("");
const chatDraft = ref("");
const catFilter = ref<string | null>(null);
const busy = ref(false);
const error = ref("");
const transcriptEl = ref<HTMLElement | null>(null);
let poll: ReturnType<typeof setInterval> | null = null;

// new-project source form (only shown when pid is null)
const srcName = ref("");
const format = ref<"plain" | "chat">("plain");
const pasted = ref("");
const files = ref<{ uri: string; text: string }[]>([]);
const sourceFiles = computed(() => {
  const out = [...files.value];
  if (pasted.value.trim()) out.push({ uri: "pasted.txt", text: pasted.value });
  return out;
});
async function onFiles(e: Event) {
  const list = (e.target as HTMLInputElement).files;
  if (!list) return;
  const out: { uri: string; text: string }[] = [];
  for (const f of Array.from(list)) out.push({ uri: f.name, text: await f.text() });
  files.value = [...files.value, ...out];
}

const STEPS = computed(() => [
  { key: "goal", label: t("stepGoal") },
  { key: "scenario", label: t("stepScenario") },
  { key: "entities", label: t("stepEntities") },
  { key: "layers", label: t("stepLayers") },
  { key: "model", label: t("stepModel") },
  { key: "summary", label: t("stepSummary") },
  { key: "done", label: t("stepDone") },
]);

const selected = computed<RankedScenario | null>(
  () => session.value?.scenarios.find((r) => r.scenario.id === session.value?.selectedScenarioId) ?? null,
);
const categories = computed(() => [...new Set((session.value?.scenarios ?? []).map((r) => scCat(r.scenario)))]);
const visibleScenarios = computed(() =>
  (session.value?.scenarios ?? []).filter((r) => !catFilter.value || scCat(r.scenario) === catFilter.value),
);
const detectedTypes = computed(() => Object.entries(session.value?.profile?.entityTypes ?? {}).sort((a, b) => b[1] - a[1]));

// messages typed before the project exists live here; flushed to the session
// on project creation so the /graphcraft agent picks up the history.
const localNotes = ref<{ by: string; at: string; text: string; step?: number }[]>([]);
const allNotes = computed(() => (pid.value ? session.value?.assistantNotes ?? [] : localNotes.value));

const notesByStep = computed(() => {
  const map: Record<number, { by: string; at: string; text: string; step?: number }[]> = {};
  for (const n of allNotes.value) {
    const s = Math.min(Math.max(1, n.step ?? revealed.value), revealed.value);
    (map[s] ??= []).push(n);
  }
  return map;
});

const quickQs = computed<string[]>(() => {
  const k = STEPS.value[revealed.value - 1]?.key;
  if (k === "scenario") return [t("qWhatScenario"), t("qWhichFits"), t("qCanCombine")];
  if (k === "entities") return [t("qWhyType"), t("qAddType"), t("qWhatExtracted")];
  if (k === "layers") return [t("qWhatCommunities"), t("qWhichAxis")];
  if (k === "model") return [t("qKeylessVsLlm"), t("qHowLong")];
  if (k === "summary" || k === "done") return [t("qHowItWorks")];
  return [t("qHowItWorks"), t("qWhatData")];
});

function scrollDown() {
  nextTick(() => {
    const el = transcriptEl.value;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  });
}
function jumpTo(i: number) {
  if (i > revealed.value) return;
  document.getElementById(`setupblk-${i}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
}
function reveal(n: number) {
  revealed.value = Math.max(revealed.value, Math.min(STEPS.value.length, n));
  scrollDown();
}

function mergeFromServer(s: SetupSession) {
  const prev = session.value;
  session.value = s;
  if (!prev) {
    if (s.goal) goalDraft.value = s.goal;
    if (s.graphName) graphNameDraft.value = s.graphName;
  } else if (s.graphName && !graphNameDraft.value) {
    graphNameDraft.value = s.graphName;
  }
}

async function refresh() {
  if (!pid.value) return;
  try {
    const before = session.value?.assistantNotes.length ?? 0;
    mergeFromServer(await api.getSetup(pid.value));
    if ((session.value?.assistantNotes.length ?? 0) > before) scrollDown();
  } catch {
    /* hub down */
  }
}
function startPoll() {
  if (!poll) poll = setInterval(refresh, 2500);
}

onMounted(async () => {
  if (pid.value) {
    await refresh();
    if (session.value?.profile) revealed.value = Math.max(6, session.value.step || 6);
    startPoll();
  }
});
onUnmounted(() => poll && clearInterval(poll));

// step 1 primary action: create the project (if new) then analyze the corpus
async function startFlow() {
  error.value = "";
  busy.value = true;
  try {
    if (!pid.value) {
      if (!sourceFiles.value.length) {
        error.value = t("needSource");
        return;
      }
      const proj = await api.createProject({
        name: srcName.value || "project",
        parse: { format: format.value, perMessage: true },
        files: sourceFiles.value,
      });
      pid.value = proj.id;
      projName.value = srcName.value || proj.id;
      // carry any pre-project chat into the live session for /graphcraft
      for (const n of localNotes.value) {
        try { await api.setupNote(pid.value, n.text, n.step, n.by); } catch { /* ignore */ }
      }
      localNotes.value = [];
      startPoll();
    }
    mergeFromServer(await api.setupAnalyze(pid.value, { goal: goalDraft.value, llm: true }));
    reveal(2);
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

async function patch(p: Parameters<typeof api.patchSetup>[1]) {
  if (!pid.value) return;
  try {
    mergeFromServer(await api.patchSetup(pid.value, p));
  } catch (e) {
    error.value = String(e);
  }
}
const selectScenario = (id: string) => patch({ selectedScenarioId: id });
function toggleType(tp: string) {
  const cur = new Set(session.value?.confirmedTypes ?? []);
  cur.has(tp) ? cur.delete(tp) : cur.add(tp);
  patch({ confirmedTypes: [...cur] });
}

async function send(text: string) {
  const msg = text.trim();
  if (!msg) return;
  chatDraft.value = "";
  if (!pid.value) {
    // no project yet → chat statelessly, keep the thread locally (flushed on create)
    const hist = localNotes.value.slice(-8).map((n) => ({ role: isAgent(n.by) ? "assistant" : "user", content: n.text }));
    localNotes.value.push({ by: "user:anon", at: new Date().toISOString(), text: msg, step: revealed.value });
    scrollDown();
    try {
      const { reply, provider } = await api.chatGeneric(msg, hist);
      if (reply) localNotes.value.push({ by: `agent:${provider}`, at: new Date().toISOString(), text: reply, step: revealed.value });
      scrollDown();
    } catch {
      /* ignore */
    }
    return;
  }
  try {
    mergeFromServer(await api.setupChat(pid.value, msg, revealed.value));
    scrollDown();
  } catch {
    /* ignore */
  }
}

function goNext(i: number) {
  if (i === 1) return startFlow();
  reveal(i + 1);
}

async function build() {
  if (!session.value || !pid.value) return;
  error.value = "";
  busy.value = true;
  try {
    if (graphNameDraft.value && graphNameDraft.value !== session.value.graphName) await patch({ graphName: graphNameDraft.value });
    const { id } = await api.setupBuild(pid.value);
    emit("built", id);
  } catch (e) {
    error.value = String(e);
    busy.value = false;
  }
}

const stepKey = (i: number) => STEPS.value[i - 1]?.key;
function fmtDate(s: string | null) {
  if (!s) return "—";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s : d.toLocaleDateString();
}
const isAgent = (by: string) => by.startsWith("agent");
const noteAuthor = (by: string) => (isAgent(by) ? "🤖 Claude" : t("you"));
</script>

<template>
  <div class="backdrop" @click.self="emit('close')">
    <div class="flow">
      <!-- conversation column -->
      <div class="main">
        <header class="fhead">
          <span class="ava sm">🤖</span>
          <strong>{{ t("assistant") }}</strong>
          <span class="muted small">· {{ projName || t("newProject") }} / {{ t("setupGraph") }}</span>
          <div class="sp" />
          <button class="x" @click="emit('close')">✕</button>
        </header>

        <div ref="transcriptEl" class="transcript">
          <template v-for="i in revealed" :key="i">
            <div :id="`setupblk-${i}`" class="turn">
              <span class="ava">🤖</span>
              <div class="bubble">
                <!-- 1 · WELCOME (+ SOURCE if new project) + GOAL -->
                <template v-if="stepKey(i) === 'goal'">
                  <h3>{{ t("welcomeTitle") }}</h3>
                  <p class="lead">{{ t("welcomeLead") }}</p>
                  <div class="howcards">
                    <div class="howcard"><strong>① {{ t("howScenarioT") }}</strong><span class="muted small">{{ t("howScenarioD") }}</span></div>
                    <div class="howcard"><strong>② {{ t("howGraphT") }}</strong><span class="muted small">{{ t("howGraphD") }}</span></div>
                    <div class="howcard"><strong>③ {{ t("howCurateT") }}</strong><span class="muted small">{{ t("howCurateD") }}</span></div>
                  </div>

                  <!-- source form: only for a brand-new project -->
                  <template v-if="!pid">
                    <label class="lab">{{ t("graphName") }}</label>
                    <input v-model="srcName" class="inp" :placeholder="t('graphNamePh')" />
                    <label class="lab">{{ t("sourceFormat") }}</label>
                    <div class="chips">
                      <button class="chip" :class="{ on: format === 'plain' }" @click="format = 'plain'">📄 {{ t("fmtPlain") }}</button>
                      <button class="chip" :class="{ on: format === 'chat' }" @click="format = 'chat'">💬 {{ t("fmtChat") }}</button>
                    </div>
                    <label class="lab">{{ t("pasteText") }}</label>
                    <textarea v-model="pasted" class="ta" rows="4" :placeholder="t('pastePh')" />
                    <label class="lab">{{ t("orFiles") }}</label>
                    <input type="file" multiple @change="onFiles" />
                    <div class="muted small">{{ sourceFiles.length }} {{ t("filesReady") }}</div>
                  </template>

                  <label class="lab">{{ t("goalTitle") }}</label>
                  <textarea v-model="goalDraft" class="ta" rows="2" :placeholder="t('goalPh')" />
                  <div class="chips">
                    <button v-for="(g, k) in goalChips" :key="k" class="chip" :class="{ on: goalDraft === g }" @click="goalDraft = g">{{ g }}</button>
                  </div>
                  <div class="hint muted small">{{ t("goalHint") }}</div>
                  <button class="btn primary" :disabled="busy || (!pid && !sourceFiles.length)" @click="goNext(1)">
                    {{ busy ? "…" : pid ? t("pickScenarios") : t("createProjectNext") }}
                  </button>
                </template>

                <!-- 2 · SCENARIO -->
                <template v-else-if="stepKey(i) === 'scenario'">
                  <h3>{{ t("scenarioTitle") }}</h3>
                  <p class="lead">{{ t("scenarioLead") }}</p>
                  <div v-if="categories.length" class="cats">
                    <button class="cat" :class="{ on: !catFilter }" @click="catFilter = null">{{ t("allCats") }}</button>
                    <button v-for="c in categories" :key="c" class="cat" :class="{ on: catFilter === c }" @click="catFilter = c">{{ c }}</button>
                  </div>
                  <div class="cards">
                    <button
                      v-for="r in visibleScenarios"
                      :key="r.scenario.id"
                      class="scard"
                      :class="{ sel: r.scenario.id === session?.selectedScenarioId }"
                      @click="selectScenario(r.scenario.id)"
                    >
                      <div class="srow">
                        <span class="sico">{{ r.scenario.icon }}</span>
                        <strong class="stitle">{{ scTitle(r.scenario) }}</strong>
                        <span v-if="r.recommended" class="reco">★ {{ t("recommended") }}</span>
                      </div>
                      <div class="ssub muted">{{ scSub(r.scenario) }}</div>
                      <ul class="why"><li v-for="(w, k) in r.why.slice(0, 2)" :key="k">✓ {{ whyText(w) }}</li></ul>
                      <div class="answers"><span v-for="(a, k) in scAns(r.scenario).slice(0, 3)" :key="k" class="ans">{{ a }}</span></div>
                    </button>
                  </div>
                  <button v-if="i === revealed" class="btn primary" :disabled="!session?.selectedScenarioId" @click="goNext(2)">{{ t("next") }} →</button>
                </template>

                <!-- 3 · ENTITIES -->
                <template v-else-if="stepKey(i) === 'entities'">
                  <h3>{{ t("entitiesTitle") }}</h3>
                  <p class="lead">{{ t("entitiesLead") }}</p>
                  <label class="lab">✨ {{ t("detectedTypes") }}</label>
                  <div class="chips">
                    <button
                      v-for="[tp, n] in detectedTypes"
                      :key="tp"
                      class="chip"
                      :class="{ on: session?.confirmedTypes.includes(tp) }"
                      @click="toggleType(tp)"
                    >{{ tp }} <span class="muted">{{ n }}</span></button>
                    <span v-if="!detectedTypes.length" class="muted small">{{ t("noTypes") }}</span>
                  </div>
                  <label class="lab">{{ t("scenarioRelations") }}</label>
                  <div class="chips"><span v-for="rl in selected?.scenario.relations ?? []" :key="rl" class="chip ghost">{{ rl }}</span></div>
                  <button v-if="i === revealed" class="btn primary" @click="goNext(3)">{{ t("next") }} →</button>
                </template>

                <!-- 4 · LAYERS & COMMUNITIES -->
                <template v-else-if="stepKey(i) === 'layers'">
                  <h3>{{ t("layersTitle") }}</h3>
                  <p class="lead">{{ t("layersLead") }}</p>
                  <label class="opt">
                    <input type="checkbox" :checked="session?.communities" @change="patch({ communities: ($event.target as HTMLInputElement).checked })" />
                    <span><strong>◎ {{ t("showCommunities") }}</strong><br /><span class="muted small">{{ t("communitiesHint") }}</span></span>
                  </label>
                  <label class="lab">{{ t("temporalAxis") }}</label>
                  <div class="chips">
                    <button class="chip" :class="{ on: session?.axis === 'tx' }" @click="patch({ axis: 'tx' })">{{ t("axisTx") }}</button>
                    <button class="chip" :class="{ on: session?.axis === 'valid' }" @click="patch({ axis: 'valid' })">{{ t("axisValid") }}</button>
                  </div>
                  <div v-if="session?.axis === 'valid' && !(session?.profile?.timeSpan.dated)" class="warn small">{{ t("noDatesWarn") }}</div>
                  <button v-if="i === revealed" class="btn primary" @click="goNext(4)">{{ t("next") }} →</button>
                </template>

                <!-- 5 · MODEL -->
                <template v-else-if="stepKey(i) === 'model'">
                  <h3>{{ t("modelTitle") }}</h3>
                  <p class="lead">{{ t("modelLead") }}</p>
                  <button class="opt big" :class="{ sel: session?.extractor === 'lightrag' }" @click="patch({ extractor: 'lightrag' })">
                    <strong>🧠 LightRAG (LLM)</strong><span class="muted small">{{ t("lightragDesc") }}</span>
                  </button>
                  <button class="opt big" :class="{ sel: session?.extractor === 'keyless' }" @click="patch({ extractor: 'keyless' })">
                    <strong>⚡ {{ t("keyless") }}</strong><span class="muted small">{{ t("keylessDesc") }}</span>
                  </button>
                  <button v-if="i === revealed" class="btn primary" @click="goNext(5)">{{ t("next") }} →</button>
                </template>

                <!-- 6 · SUMMARY -->
                <template v-else-if="stepKey(i) === 'summary'">
                  <h3>{{ t("summaryTitle") }}</h3>
                  <label class="lab">{{ t("graphName") }}</label>
                  <input v-model="graphNameDraft" class="inp" :placeholder="t('graphNamePh')" />
                  <dl class="sum">
                    <div><dt>{{ t("stepScenario") }}</dt><dd>{{ selected ? `${selected.scenario.icon} ${scTitle(selected.scenario)}` : "—" }}</dd></div>
                    <div><dt>{{ t("stepEntities") }}</dt><dd>{{ session?.confirmedTypes.join(", ") || "—" }}</dd></div>
                    <div><dt>◎</dt><dd>{{ session?.communities ? t("on") : t("off") }}</dd></div>
                    <div><dt>{{ t("temporalAxis") }}</dt><dd>{{ session?.axis === "valid" ? t("axisValid") : t("axisTx") }}</dd></div>
                    <div><dt>{{ t("stepModel") }}</dt><dd>{{ session?.extractor === "lightrag" ? "LightRAG" : t("keyless") }}</dd></div>
                    <div><dt>{{ t("documents") }}</dt><dd>{{ session?.profile?.docCount }} · ≈{{ session?.profile?.estChunks }} {{ t("chunks") }}</dd></div>
                  </dl>
                  <p class="muted small">{{ t("summaryNote") }}</p>
                  <button v-if="i === revealed" class="btn primary" @click="goNext(6)">{{ t("next") }} →</button>
                </template>

                <!-- 7 · BUILD -->
                <template v-else>
                  <h3>{{ t("buildTitle") }}</h3>
                  <p class="lead">{{ t("buildLead", { name: graphNameDraft || (selected ? scTitle(selected.scenario) : "") }) }}</p>
                  <button class="btn primary big-btn" :disabled="busy" @click="build">{{ busy ? t("building") : "▶ " + t("createBuild") }}</button>
                </template>
              </div>
            </div>

            <template v-for="(n, k) in (notesByStep[i] ?? [])" :key="`${i}-${k}`">
              <div class="turn" :class="{ me: !isAgent(n.by) }">
                <span class="ava">{{ isAgent(n.by) ? "🤖" : "🧑" }}</span>
                <div class="bubble chat" :class="{ agent: isAgent(n.by) }">
                  <span class="who muted small">{{ noteAuthor(n.by) }}</span>
                  <div>{{ n.text }}</div>
                </div>
              </div>
            </template>
          </template>

          <p v-if="error" class="err">{{ error }}</p>
        </div>

        <!-- pinned chat input -->
        <div class="inbar">
          <div class="quick">
            <button v-for="(q, k) in quickQs" :key="k" class="qchip" @click="send(q)">{{ q }}</button>
          </div>
          <div class="cin">
            <input v-model="chatDraft" class="inp" :placeholder="t('assistantPh')" @keyup.enter="send(chatDraft)" />
            <button class="btn primary" @click="send(chatDraft)">↵</button>
          </div>
        </div>
      </div>

      <!-- stepper rail (jump index) -->
      <aside class="rail">
        <ol>
          <li
            v-for="(s, i) in STEPS"
            :key="s.key"
            :class="{ on: revealed === i + 1, done: revealed > i + 1, locked: i + 1 > revealed }"
            @click="jumpTo(i + 1)"
          >
            <span class="num">{{ revealed > i + 1 ? "✓" : i + 1 }}</span>
            <span class="lbl">{{ s.label }}</span>
          </li>
        </ol>
        <div v-if="session?.profile" class="pcard">
          <div class="muted small">{{ t("corpus") }}</div>
          <div>{{ session.profile.docCount }} {{ t("documents") }}</div>
          <div class="muted small">{{ session.profile.languages.map((l) => l.lang.toUpperCase()).join(" · ") }}</div>
          <div v-if="session.profile.timeSpan.from" class="muted small">{{ fmtDate(session.profile.timeSpan.from) }} → {{ fmtDate(session.profile.timeSpan.to) }}</div>
          <div v-if="session.profile.authors.length" class="muted small">{{ session.profile.authors.length }} {{ t("authors") }}</div>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.backdrop { position: fixed; inset: 0; background: var(--gc-bg, #f6f7f9); z-index: 3000; }
.flow { display: flex; background: var(--gc-panel); color: var(--gc-fg); width: 100%; height: 100%; overflow: hidden; }
.main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.fhead { display: flex; align-items: center; gap: 8px; padding: 12px 18px; border-bottom: 1px solid var(--gc-border); }
.x { border: none; background: transparent; cursor: pointer; font-size: 16px; color: var(--gc-muted, #80868b); }
.sp { flex: 1; }
.transcript { flex: 1; overflow: auto; padding: 18px 18px 8px; display: flex; flex-direction: column; gap: 14px; background: var(--gc-bg, #f6f7f9); }
.turn { display: flex; gap: 10px; align-items: flex-start; width: min(860px, 100%); margin: 0 auto; }
.turn.me { flex-direction: row-reverse; }
.ava { width: 28px; height: 28px; border-radius: 50%; background: var(--gc-panel); border: 1px solid var(--gc-border); display: flex; align-items: center; justify-content: center; font-size: 15px; flex-shrink: 0; }
.ava.sm { width: 24px; height: 24px; font-size: 13px; }
.bubble { background: var(--gc-panel); border: 1px solid var(--gc-border); border-radius: 12px; padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; max-width: 640px; flex: 1; }
.bubble.chat { flex: 0 1 auto; max-width: 75%; }
.bubble.chat.agent { background: var(--gc-accent-soft, #e8f0fe); }
.turn.me .bubble.chat { background: var(--gc-card); }
.who { font-weight: 600; }
h3 { margin: 0; font-size: 16px; }
.lead { margin: 0; color: var(--gc-muted, #5f6368); font-size: 13px; }
.lab { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--gc-muted, #80868b); margin-top: 4px; }
.inp, .ta { border: 1px solid var(--gc-border); border-radius: 8px; padding: 8px 10px; background: var(--gc-bg, #fff); color: var(--gc-fg); font: inherit; }
.ta { resize: vertical; }
.hint { margin-top: 2px; }
.howcards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.howcard { border: 1px solid var(--gc-border); background: var(--gc-card); border-radius: 10px; padding: 8px 10px; display: flex; flex-direction: column; gap: 3px; }
.howcard strong { font-size: 12px; }
.cats { display: flex; flex-wrap: wrap; gap: 6px; }
.cat { border: 1px solid var(--gc-border); background: var(--gc-card); color: var(--gc-fg); border-radius: 14px; padding: 3px 12px; cursor: pointer; font-size: 12px; }
.cat.on { background: var(--gc-accent); border-color: var(--gc-accent); color: #fff; }
.cards { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.scard { text-align: left; border: 1px solid var(--gc-border); background: var(--gc-card); border-radius: 12px; padding: 12px; cursor: pointer; display: flex; flex-direction: column; gap: 6px; transition: border-color 0.12s; }
.scard:hover { border-color: var(--gc-accent); }
.scard.sel { border-color: var(--gc-accent); box-shadow: 0 0 0 2px var(--gc-accent) inset; }
.srow { display: flex; align-items: center; gap: 7px; }
.sico { font-size: 18px; }
.stitle { flex: 1; font-size: 14px; }
.reco { font-size: 10px; background: #fef7e0; color: #b06000; border-radius: 8px; padding: 1px 6px; white-space: nowrap; }
.ssub { font-size: 12px; }
.why { list-style: none; margin: 0; padding: 0; font-size: 11px; color: #1e8e3e; }
.answers { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 2px; }
.ans { font-size: 10px; border: 1px solid var(--gc-border); border-radius: 8px; padding: 1px 6px; color: var(--gc-muted, #5f6368); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { border: 1px solid var(--gc-border); background: var(--gc-card); color: var(--gc-fg); border-radius: 14px; padding: 3px 10px; cursor: pointer; font-size: 12px; }
.chip.on { background: var(--gc-accent); border-color: var(--gc-accent); color: #fff; }
.chip.ghost { cursor: default; }
.opt { display: flex; align-items: flex-start; gap: 8px; border: 1px solid var(--gc-border); border-radius: 10px; padding: 10px; cursor: pointer; background: var(--gc-card); }
.opt.big { flex-direction: column; gap: 3px; width: 100%; text-align: left; }
.opt.sel { border-color: var(--gc-accent); box-shadow: 0 0 0 2px var(--gc-accent) inset; }
.sum { margin: 4px 0; display: grid; gap: 6px; }
.sum > div { display: flex; gap: 10px; }
.sum dt { color: var(--gc-muted, #80868b); width: 130px; font-size: 12px; }
.sum dd { margin: 0; font-weight: 600; font-size: 13px; }
.warn { color: #b06000; } .err { color: #c5221f; font-size: 12px; }
.btn { border: 1px solid var(--gc-border); background: var(--gc-card); color: var(--gc-fg); border-radius: 8px; padding: 6px 14px; cursor: pointer; font: inherit; align-self: flex-start; }
.btn.primary { background: var(--gc-accent); border-color: var(--gc-accent); color: #fff; }
.btn:disabled { opacity: 0.5; cursor: default; }
.big-btn { font-size: 15px; padding: 10px 18px; }
.inbar { border-top: 1px solid var(--gc-border); padding: 8px 14px 10px; display: flex; flex-direction: column; gap: 6px; background: var(--gc-panel); }
.quick, .cin { width: min(860px, 100%); margin: 0 auto; }
.quick { display: flex; flex-wrap: wrap; gap: 5px; }
.qchip { border: 1px solid var(--gc-border); background: var(--gc-bg, #f6f7f9); border-radius: 12px; padding: 2px 9px; cursor: pointer; font-size: 11px; color: var(--gc-muted, #5f6368); }
.cin { display: flex; gap: 6px; }
.cin .inp { flex: 1; }
.cin .btn { align-self: stretch; }
.rail { width: 210px; border-left: 1px solid var(--gc-border); background: var(--gc-bg, #f6f7f9); padding: 16px 14px; overflow: auto; }
.rail ol { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.rail li { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 8px; font-size: 13px; color: var(--gc-muted, #80868b); cursor: pointer; }
.rail li.locked { opacity: 0.5; cursor: default; }
.rail li.on { background: var(--gc-panel); color: var(--gc-fg); font-weight: 600; }
.rail li.done { color: #1e8e3e; }
.num { width: 20px; height: 20px; border-radius: 50%; border: 1px solid currentColor; display: flex; align-items: center; justify-content: center; font-size: 11px; flex-shrink: 0; }
.rail li.on .num { background: var(--gc-accent); border-color: var(--gc-accent); color: #fff; }
.pcard { margin-top: 16px; padding: 10px; border: 1px solid var(--gc-border); border-radius: 10px; background: var(--gc-panel); display: flex; flex-direction: column; gap: 2px; font-size: 12px; }
.muted { color: var(--gc-muted, #80868b); } .small { font-size: 11px; }
</style>
