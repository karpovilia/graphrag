<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "@/lib/api";
import SetupFlow from "@/components/SetupFlow.vue";

const emit = defineEmits<{ (e: "open", id: string): void }>();
const { t } = useI18n();

const projects = ref<Awaited<ReturnType<typeof api.listProjects>>>([]);
const selected = ref<Awaited<ReturnType<typeof api.getProject>> | null>(null);
// AI-led setup conversation target. id=null → new project (the flow creates it
// in its first turn); id set → build another graph in an existing project.
const setupTarget = ref<{ id: string | null; name: string } | null>(null);

async function loadProjects() {
  try { projects.value = await api.listProjects(); } catch { /* hub down */ }
}
onMounted(loadProjects);

async function openProject(id: string) {
  if (id === "_legacy") {
    const graphs = (await api.listGraphs()).filter((g) => !(g as { projectId?: string }).projectId);
    selected.value = { id: "_legacy", name: t("legacyGraphs"), parse: { format: "-", chunkSize: 0, chunkOverlap: 0 }, documentCount: 0, graphs };
  } else {
    selected.value = await api.getProject(id);
  }
}
function startSetup(id: string | null, name: string) {
  setupTarget.value = { id, name };
}
async function delProject(p: { id: string; name: string; graphCount?: number }) {
  if (!confirm(t("confirmDelProject", { name: p.name, n: p.graphCount ?? 0 }))) return;
  await api.deleteProject(p.id);
  await loadProjects();
}
async function delGraph(g: { id: string; name: string }) {
  if (!confirm(t("confirmDelGraph", { name: g.name }))) return;
  await api.deleteGraph(g.id);
  if (selected.value) await openProject(selected.value.id);
  await loadProjects();
}
</script>

<template>
  <div class="home">
    <header class="hh">
      <strong class="brand" :class="{ link: selected }" @click="selected = null">{{ t("app") }}</strong>
      <span v-if="selected" class="muted">/ {{ selected.name }}</span>
      <span v-else class="muted">{{ t("projectsHeading") }}</span>
      <div class="sp" />
      <button v-if="!selected" class="btn primary" @click="startSetup(null, '')">＋ {{ t("newProject") }}</button>
    </header>

    <!-- PROJECTS -->
    <div v-if="!selected" class="grid">
      <button class="card new" @click="startSetup(null, '')">
        <div class="plus">＋</div>
        <div>{{ t("newProject") }}</div>
        <div class="muted small">{{ t("streamHint") }}</div>
      </button>
      <button v-for="p in projects" :key="p.id" class="card" @click="openProject(p.id)">
        <span v-if="p.id !== '_legacy'" class="del" :title="t('delete')" @click.stop="delProject(p)">✕</span>
        <div class="ch"><span class="name">{{ p.name }}</span></div>
        <dl class="metrics">
          <div><dt>{{ t("documents") }}</dt><dd>{{ p.documentCount }}</dd></div>
          <div><dt>{{ t("graphs") }}</dt><dd>{{ p.graphCount }}</dd></div>
        </dl>
        <div class="chips"><span class="chip">{{ p.parse.format }}</span><span v-if="p.source" class="chip muted">{{ p.source }}</span></div>
      </button>
    </div>

    <!-- GRAPHS OF A PROJECT -->
    <div v-else class="grid">
      <button v-if="selected.id !== '_legacy'" class="card new" @click="startSetup(selected.id, selected.name)">
        <div class="plus">＋</div>
        <div>{{ t("newGraphIn") }}</div>
        <div class="muted small">{{ t("setupHint") }}</div>
      </button>
      <button v-for="g in selected.graphs" :key="g.id" class="card" @click="emit('open', g.id)">
        <span class="del" :title="t('delete')" @click.stop="delGraph(g)">✕</span>
        <div class="ch"><span class="name">{{ g.name }}</span></div>
        <dl class="metrics">
          <div><dt>{{ t("nodes") }}</dt><dd>{{ g.nodeCount }}</dd></div>
          <div><dt>{{ t("edges") }}</dt><dd>{{ g.edgeCount }}</dd></div>
        </dl>
        <div class="chips"><span v-for="l in g.layersPresent" :key="l" class="chip">{{ l }}</span></div>
      </button>
      <p v-if="!selected.graphs.length && selected.id === '_legacy'" class="muted">—</p>
    </div>

    <SetupFlow
      v-if="setupTarget"
      :project-id="setupTarget.id"
      :project-name="setupTarget.name"
      @close="setupTarget = null"
      @built="(id) => emit('open', id)"
    />
  </div>
</template>

<style scoped>
.home { height: 100vh; overflow: auto; background: var(--gc-bg, #f6f7f9); }
.hh { display: flex; align-items: center; gap: 10px; padding: 14px 22px; border-bottom: 1px solid var(--gc-border); background: var(--gc-panel); position: sticky; top: 0; z-index: 2; }
.brand { font-size: 16px; }
.brand.link { cursor: pointer; }
.brand.link:hover { color: var(--gc-accent); }
.sp { flex: 1; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; padding: 22px; }
.card { text-align: left; background: var(--gc-panel); border: 1px solid var(--gc-border); border-radius: 12px; padding: 14px; cursor: pointer; color: var(--gc-fg); display: flex; flex-direction: column; gap: 8px; transition: box-shadow 0.12s, border-color 0.12s; }
.card { position: relative; }
.card:hover { box-shadow: 0 6px 20px rgba(0,0,0,0.1); border-color: var(--gc-accent); }
.del { position: absolute; top: 6px; right: 8px; color: var(--gc-muted, #b0b4bb); font-size: 13px; cursor: pointer; opacity: 0; transition: opacity 0.1s; }
.card:hover .del { opacity: 1; }
.del:hover { color: #c5221f; }
.card.new { align-items: center; justify-content: center; text-align: center; border-style: dashed; color: var(--gc-accent); min-height: 130px; }
.card.new.col { align-items: stretch; cursor: default; gap: 6px; }
.plus { font-size: 28px; }
.ch { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.name { font-weight: 600; font-size: 15px; overflow-wrap: anywhere; }
.metrics { display: flex; gap: 18px; margin: 0; }
.metrics dt { font-size: 10px; text-transform: uppercase; color: var(--gc-muted, #80868b); }
.metrics dd { margin: 0; font-size: 18px; font-weight: 600; }
.chips { display: flex; flex-wrap: wrap; gap: 4px; }
.chip { border: 1px solid var(--gc-border); border-radius: 10px; padding: 0 7px; font-size: 11px; color: var(--gc-muted, #5f6368); }
.inp { border: 1px solid var(--gc-border); border-radius: 6px; padding: 5px 8px; background: var(--gc-bg, #fff); color: var(--gc-fg); }
.llm { font-size: 12px; display: flex; gap: 6px; align-items: center; }
.muted { color: var(--gc-muted, #80868b); } .small { font-size: 12px; }
</style>
