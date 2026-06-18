<script setup lang="ts">
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api, type GraphView } from "@/lib/api";

const props = defineProps<{
  graphId: string;
  view: GraphView;
  selection: string[];
  /** A question posted to the console (by anyone) → shows a pending turn. */
  incomingAsk?: { id: string; question: string; by: string; seq: number } | null;
  /** The agent's answer → fills the matching pending turn. */
  incomingAnswer?: {
    id: string;
    answer: string;
    entities?: { id: string; name: string }[];
    paths?: string[];
    sources?: { id: string; documentId: string | null; text: string }[];
    by: string;
    seq: number;
  } | null;
  /** Agent-proposed questions (newest first) → clickable chips. */
  suggestedQuestions?: { id: string; text: string; rationale?: string; seedNodeIds?: string[] }[];
}>();
const emit = defineEmits<{ (e: "focus", ids: string[]): void; (e: "select-node", id: string): void }>();
const { t } = useI18n();

interface Turn {
  id?: string;
  q: string;
  algorithm: string;
  /** Which model the request was routed to (server-reported for direct LLM
   *  calls, or the selected model for the agent/claude-subscription flow). */
  model?: string;
  answer?: string;
  sources?: { id: string; documentId: string | null; text: string }[];
  entities?: { id: string; name: string }[];
  communities?: { id: string; name: string }[];
  paths?: string[];
  busy?: boolean;
  error?: string;
}
const turns = ref<Turn[]>([]);
const draft = ref("");

// config (persisted across sessions)
const savedCfg = JSON.parse(localStorage.getItem("gc:ragCfg") || "{}");
const algorithm = ref<"lightrag" | "ms-graphrag" | "tog">(savedCfg.algorithm ?? "lightrag");
const useDate = ref(!!savedCfg.useDate);
const useKinds = ref(!!savedCfg.useKinds);
const useSelection = ref(!!savedCfg.useSelection);
const model = ref(savedCfg.model ?? "claude-subscription");
const cfgOpen = ref(false);
watch([algorithm, useDate, useKinds, useSelection, model], () => {
  localStorage.setItem("gc:ragCfg", JSON.stringify({
    algorithm: algorithm.value, useDate: useDate.value, useKinds: useKinds.value, useSelection: useSelection.value, model: model.value,
  }));
});

// when a group is selected, prefill "tell me about these nodes" (+ scope to it)
watch(
  () => props.selection.length,
  (n, prev) => {
    if (n > 0 && (prev ?? 0) === 0 && !draft.value.trim()) {
      draft.value = t("ragAboutThese");
      useSelection.value = true;
    }
  },
);

// query history (persisted)
const history = ref<string[]>(JSON.parse(localStorage.getItem("gc:ragHistory") || "[]"));
function remember(q: string) {
  history.value = [q, ...history.value.filter((x) => x !== q)].slice(0, 25);
  localStorage.setItem("gc:ragHistory", JSON.stringify(history.value));
}
const histOpen = ref(false);
function clearHistory() { history.value = []; localStorage.removeItem("gc:ragHistory"); histOpen.value = false; }

const ALGOS: { id: "lightrag" | "ms-graphrag" | "tog"; label: string }[] = [
  { id: "lightrag", label: "LightRAG" },
  { id: "ms-graphrag", label: "MS GraphRAG" },
  { id: "tog", label: "Think-on-Graph" },
];
// "claude-subscription" = answer via the live agent/terminal session (current
// human-in-the-loop flow). Any other model = direct server-side LLM call.
const CLAUDE_SUB = "claude-subscription";
const MODELS: { id: string; label: string }[] = [
  { id: CLAUDE_SUB, label: "Claude (subscription)" },
  { id: "deepseek-chat", label: "deepseek-chat" },
  { id: "deepseek-reasoner", label: "deepseek-reasoner" },
];
const EXAMPLES = ["qExWho", "qExThemes", "qExHow", "qExRisks"];

let localSeq = 0;
// Ask routes by model:
//  • "claude-subscription" → the live agent / terminal session (human-in-the-
//    loop). The turn is created from the rag_ask broadcast and filled by the
//    agent's rag_answer.
//  • any other model → a direct server-side LLM call (DeepSeek …). We own the
//    turn locally and fill it from the HTTP response — the terminal is NOT used.
async function ask(q: string) {
  const question = q.trim();
  if (!question) return;
  draft.value = "";
  remember(question);
  const cfg = {
    algorithm: algorithm.value,
    model: model.value,
    useDate: useDate.value,
    useKinds: useKinds.value,
    useSelection: useSelection.value,
    selection: props.selection,
    view: { from: props.view.from, to: props.view.to, types: props.view.types, axis: props.view.axis },
  };

  if (model.value !== CLAUDE_SUB) {
    const id = `local-${++localSeq}`;
    turns.value.push({ id, q: question, algorithm: algorithm.value, model: model.value, busy: true });
    const i = turns.value.findIndex((t) => t.id === id);
    try {
      const r = await api.ask(props.graphId, question, cfg);
      turns.value[i] = {
        id, q: question, algorithm: r.algorithm ?? algorithm.value, model: r.model ?? model.value,
        answer: r.answer, entities: r.usedEntities, communities: r.usedCommunities,
        paths: r.paths, sources: r.sources,
      };
      if (r.usedEntities?.length) emit("focus", r.usedEntities.map((e) => e.id));
    } catch (e) {
      turns.value[i] = { id, q: question, algorithm: algorithm.value, model: model.value, error: String(e) };
    }
    return;
  }

  try {
    await api.ragAsk(props.graphId, question, cfg);
  } catch (e) {
    turns.value.push({ q: question, algorithm: algorithm.value, model: model.value, error: String(e) });
  }
}

// a question landed in the console (mine or another participant's) → pending turn
watch(
  () => props.incomingAsk?.seq,
  () => {
    const a = props.incomingAsk;
    if (!a || turns.value.some((t) => t.id === a.id)) return;
    turns.value.push({ id: a.id, q: a.question, algorithm: algorithm.value, model: model.value, busy: true });
  },
);

// the agent answered → fill the matching turn (and highlight the entities it used)
watch(
  () => props.incomingAnswer?.seq,
  () => {
    const ans = props.incomingAnswer;
    if (!ans) return;
    const i = turns.value.findIndex((t) => t.id === ans.id);
    const filled: Turn = {
      id: ans.id,
      q: i >= 0 ? turns.value[i]!.q : "",
      algorithm: i >= 0 ? turns.value[i]!.algorithm : algorithm.value,
      model: i >= 0 ? turns.value[i]!.model : model.value,
      answer: ans.answer,
      entities: ans.entities,
      paths: ans.paths,
      sources: ans.sources,
    };
    if (i >= 0) turns.value[i] = filled;
    else turns.value.push(filled);
    if (ans.entities?.length) emit("focus", ans.entities.map((e) => e.id));
  },
);
</script>

<template>
  <div class="rag">
    <!-- config -->
    <div class="cfg">
      <div class="cfg-row">
        <select v-model="algorithm" class="sel" :title="t('ragAlgo')">
          <option v-for="a in ALGOS" :key="a.id" :value="a.id">{{ a.label }}</option>
        </select>
        <button class="cfg-tg" :class="{ on: histOpen }" :title="t('ragRecent')" @click="histOpen = !histOpen">🕘</button>
        <button class="cfg-tg" :class="{ on: cfgOpen }" :title="t('ragConfig')" @click="cfgOpen = !cfgOpen">⚙</button>
      </div>
      <div v-if="histOpen" class="hist">
        <div v-if="!history.length" class="muted small">—</div>
        <button v-for="(h, k) in history" :key="k" class="hist-row" :title="h" @click="histOpen = false; ask(h)">{{ h }}</button>
        <button v-if="history.length" class="link sm clr" @click="clearHistory">{{ t("clear") }}</button>
      </div>
      <div v-if="cfgOpen" class="cfg-body">
        <label><input type="checkbox" v-model="useDate" /> {{ t("ragUseDate") }}</label>
        <label><input type="checkbox" v-model="useKinds" /> {{ t("ragUseKinds") }}</label>
        <label><input type="checkbox" v-model="useSelection" /> {{ t("ragUseSel") }} ({{ selection.length }})</label>
        <div class="cfg-model">
          <span class="muted small">{{ t("ragModel") }}</span>
          <select v-model="model" class="sel"><option v-for="m in MODELS" :key="m.id" :value="m.id">{{ m.label }}</option></select>
        </div>
      </div>
    </div>

    <div class="thread">
      <p v-if="!turns.length" class="muted hint">{{ t("ragHint") }}</p>
      <div v-for="(turn, i) in turns" :key="i" class="turn">
        <div class="q">❓ {{ turn.q }} <span class="algo-badge">{{ turn.algorithm }}</span><span v-if="turn.model" class="model-badge">{{ turn.model }}</span></div>
        <div v-if="turn.busy" class="muted">…</div>
        <div v-else-if="turn.error" class="err">{{ turn.error }}</div>
        <template v-else>
          <div class="a">{{ turn.answer }}</div>
          <div v-if="turn.entities?.length" class="used">
            <button v-for="e in turn.entities" :key="e.id" class="ent" @click="emit('select-node', e.id)">{{ e.name }}</button>
          </div>
          <div v-if="turn.communities?.length" class="used">
            <span v-for="c in turn.communities" :key="c.id" class="comm">◎ {{ c.name }}</span>
          </div>
          <details v-if="turn.paths?.length" class="paths">
            <summary>{{ t("ragPaths") }} ({{ turn.paths.length }})</summary>
            <div v-for="(p, k) in turn.paths" :key="k" class="path">{{ p }}</div>
          </details>
          <details v-if="turn.sources?.length" class="srcs">
            <summary>{{ t("sources") }} ({{ turn.sources.length }})</summary>
            <div v-for="s in turn.sources" :key="s.id" class="src">
              <div class="src-doc">📄 {{ s.documentId || s.id }}</div>
              <div class="src-text">{{ s.text }}</div>
            </div>
          </details>
        </template>
      </div>
    </div>

    <div v-if="suggestedQuestions?.length" class="suggested">
      <span class="muted small">🤖 Suggested:</span>
      <button
        v-for="q in suggestedQuestions.slice(0, 4)"
        :key="q.id"
        class="ex sug"
        :title="q.rationale || q.text"
        @click="ask(q.text)"
      >{{ q.text.length > 52 ? q.text.slice(0, 52) + "…" : q.text }}</button>
    </div>

    <div class="examples" v-if="!turns.length">
      <button v-for="ex in EXAMPLES" :key="ex" class="ex" @click="ask(t(ex))">{{ t(ex) }}</button>
    </div>
    <div v-if="history.length" class="recent">
      <span class="muted small">{{ t("ragRecent") }}:</span>
      <button v-for="(h, k) in history.slice(0, 8)" :key="k" class="ex" :title="h" @click="ask(h)">{{ h.length > 28 ? h.slice(0, 28) + "…" : h }}</button>
    </div>

    <div class="ask">
      <textarea
        v-model="draft"
        class="inp ta"
        rows="3"
        :placeholder="t('ragPh')"
        @keydown.enter.exact.prevent="ask(draft)"
      />
      <button class="btn primary" @click="ask(draft)">↵</button>
    </div>
  </div>
</template>

<style scoped>
.rag { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.cfg { padding: 8px 10px; border-bottom: 1px solid var(--gc-border); }
.cfg-row { display: flex; gap: 6px; align-items: center; }
.sel { border: 1px solid var(--gc-border); background: var(--gc-card); color: var(--gc-fg); border-radius: 6px; padding: 4px 6px; font: inherit; font-size: 12px; flex: 1; }
.cfg-tg { border: 1px solid var(--gc-border); background: var(--gc-card); color: var(--gc-muted, #80868b); border-radius: 6px; cursor: pointer; padding: 0 8px; }
.cfg-tg.on { color: var(--gc-accent); border-color: var(--gc-accent); }
.cfg-body { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; font-size: 12px; }
.cfg-model { display: flex; align-items: center; gap: 6px; margin-top: 2px; }
.thread { flex: 1; overflow: auto; padding: 10px; display: flex; flex-direction: column; gap: 12px; }
.hint { font-size: 13px; }
.turn { display: flex; flex-direction: column; gap: 6px; }
.q { font-weight: 600; font-size: 13px; }
.algo-badge { font-weight: 400; font-size: 10px; color: var(--gc-muted, #80868b); border: 1px solid var(--gc-border); border-radius: 8px; padding: 0 5px; }
.model-badge { font-weight: 400; font-size: 10px; color: var(--gc-accent, #1a73e8); border: 1px solid var(--gc-accent, #1a73e8); border-radius: 8px; padding: 0 5px; margin-left: 4px; }
.a { font-size: 13px; line-height: 1.5; white-space: pre-wrap; background: var(--gc-card); border-radius: 8px; padding: 8px 10px; }
.used { display: flex; flex-wrap: wrap; gap: 4px; }
.ent { border: 1px solid var(--gc-border); background: var(--gc-card); color: var(--gc-accent); border-radius: 10px; padding: 1px 8px; font-size: 11px; cursor: pointer; }
.comm { border: 1px solid var(--gc-border); border-radius: 10px; padding: 1px 8px; font-size: 11px; color: var(--gc-muted, #5f6368); }
.paths, .srcs { font-size: 12px; }
.paths > summary, .srcs > summary { cursor: pointer; color: var(--gc-accent); }
.path { font-size: 11px; color: var(--gc-muted, #5f6368); padding: 1px 0; }
.src { margin-top: 6px; }
.src-doc { font-size: 11px; color: var(--gc-muted, #80868b); }
.src-text { font-size: 12px; line-height: 1.45; background: var(--gc-card); border-radius: 6px; padding: 6px 8px; max-height: 120px; overflow: auto; white-space: pre-wrap; }
.examples { display: flex; flex-wrap: wrap; gap: 5px; padding: 0 10px 8px; }
.recent { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; padding: 0 10px 8px; }
.suggested { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; padding: 6px 10px; border-top: 1px solid var(--gc-border); max-height: 96px; overflow: auto; }
.ex.sug { color: var(--gc-accent); border-color: var(--gc-accent); }
.hist { display: flex; flex-direction: column; gap: 2px; margin-top: 6px; max-height: 180px; overflow: auto; }
.hist-row { text-align: left; border: none; background: none; color: var(--gc-fg); cursor: pointer; font: inherit; font-size: 12px; padding: 3px 4px; border-radius: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hist-row:hover { background: var(--gc-card); }
.clr { align-self: flex-start; margin-top: 4px; color: #c5221f; background: none; border: none; cursor: pointer; }
.ex { border: 1px solid var(--gc-border); background: var(--gc-bg, #f6f7f9); border-radius: 12px; padding: 3px 9px; font-size: 11px; cursor: pointer; color: var(--gc-muted, #5f6368); }
.ask { display: flex; gap: 6px; padding: 8px 10px; border-top: 1px solid var(--gc-border); align-items: flex-end; }
.ask .inp { flex: 1; border: 1px solid var(--gc-border); border-radius: 8px; padding: 7px 9px; background: var(--gc-bg, #fff); color: var(--gc-fg); font: inherit; }
.ask .ta { resize: vertical; min-height: 64px; max-height: 200px; line-height: 1.4; }
.btn { border: 1px solid var(--gc-border); background: var(--gc-card); color: var(--gc-fg); border-radius: 8px; padding: 6px 12px; cursor: pointer; }
.btn.primary { background: var(--gc-accent); border-color: var(--gc-accent); color: #fff; }
.err { color: #c5221f; font-size: 12px; }
.muted { color: var(--gc-muted, #80868b); }
</style>
