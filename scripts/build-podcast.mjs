/** data/podcast → LightRAG (full transcripts) + MS-GraphRAG community reports.
 *  Plain-JS so it runs under plain `node` (sandbox blocks the TS loader).
 *
 *  NODE_USE_ENV_PROXY=1 DSKEY_FILE=/tmp/dskey node scripts/build-podcast.mjs
 */
import { promises as fs } from "node:fs";
import path from "node:path";
import {
  buildGraph, chunkDocument, createLLM, deriveSchema, extractJson, lightRagExtractor, nowIso,
} from "/home/ki/repos/graphcraft/packages/graph-core/dist/index.js";

const DIR = "/home/ki/repos/graphcraft/data/podcast";
const PROJECTS = "/home/ki/repos/graphcraft/projects";
const GRAPHS = "/home/ki/repos/graphcraft/graphs";
const PID = process.env.KB2_PID ?? "podcast";
const GID = process.env.KB2_GID ?? "podcast-graph";
const CHUNK = Number(process.env.CHUNK ?? "8000");
const GLEAN = Number(process.env.GLEAN ?? "1");
const CONC = Number(process.env.CONC ?? "8");
const now = nowIso();

/** strip an .srt to plain text (drop indices + timestamps + dup lines). */
function stripSrt(s) {
  const out = [];
  let prev = "";
  for (const line of s.split(/\r?\n/)) {
    const t = line.trim();
    if (!t || /^\d+$/.test(t) || /-->/.test(t)) continue;
    if (t !== prev) { out.push(t); prev = t; }
  }
  return out.join(" ");
}

const cleanTitle = (f) => f.replace(/\.(en|ru|ru-orig)\.(txt|srt)$/i, "").replace(/\s*\[[^\]]+\]\s*$/, "").replace(/：/g, ":").trim();
const vid = (f) => (f.match(/\[([^\]]+)\]/)?.[1] ?? f);

/** one document per episode: prefer the clean .en.txt, else stripped .en.srt. */
async function collect() {
  const files = await fs.readdir(DIR);
  const byEp = new Map();
  for (const f of files) {
    const id = vid(f);
    const rank = /\.en\.txt$/i.test(f) ? 3 : /\.en\.srt$/i.test(f) ? 2 : /\.ru\.srt$/i.test(f) ? 1 : 0;
    if (rank === 0) continue;
    const cur = byEp.get(id);
    if (!cur || rank > cur.rank) byEp.set(id, { f, rank });
  }
  const docs = [];
  for (const { f, rank } of byEp.values()) {
    const raw = await fs.readFile(path.join(DIR, f), "utf8");
    const text = rank >= 3 ? raw : stripSrt(raw);
    if (text.length > 200) docs.push({ id: vid(f), uri: cleanTitle(f), text });
  }
  return docs;
}

const CR_SYS = `You write MS-GraphRAG community reports. Given a cluster of related entities and their relationships from a knowledge graph built over Russian tech/education podcasts, return a JSON object {"title": "...", "summary": "..."}. The title is a short, specific, human-readable name for the theme (3-7 words). The summary is 2-3 sentences describing what the community is about and how its members relate. Write BOTH title and summary in Russian. Return ONLY the JSON.`;

async function addCommunityReports(state, llm) {
  const byId = new Map(state.nodes.map((n) => [n.id, n]));
  const comms = state.nodes.filter((n) => n.layer === "community");
  const members = new Map();
  for (const e of state.edges) if (e.type === "member_of") {
    (members.get(e.targetId) ?? members.set(e.targetId, []).get(e.targetId)).push(e.sourceId);
  }
  console.log(`MS-GraphRAG: ${comms.length} community reports…`);
  let i = 0, done = 0;
  async function work() {
    while (i < comms.length) {
      const c = comms[i++];
      const ids = new Set(members.get(c.id) ?? []);
      const ents = [...ids].map((id) => byId.get(id)).filter(Boolean);
      const entLines = ents.slice(0, 40).map((m) => `- ${m.name} (${m.type})${m.summary ? ": " + m.summary : ""}`).join("\n");
      const relLines = state.edges
        .filter((e) => e.type === "entity_relation" && ids.has(e.sourceId) && ids.has(e.targetId))
        .slice(0, 40)
        .map((e) => `- ${byId.get(e.sourceId)?.name} → ${byId.get(e.targetId)?.name}${e.relation ? " (" + e.relation + ")" : ""}`)
        .join("\n");
      const prompt = `Entities:\n${entLines}\n\nRelationships:\n${relLines || "(none)"}`;
      try {
        const { text } = await llm.complete([{ role: "system", content: CR_SYS }, { role: "user", content: prompt }], { temperature: 0.2, maxTokens: 320, jsonObject: true });
        const j = extractJson(text);
        if (j && typeof j === "object") {
          if (j.title) c.name = String(j.title).slice(0, 80);
          if (j.summary) c.summary = String(j.summary);
          c.attributes = { ...c.attributes, report: true };
        }
      } catch (e) {
        console.log(`  report fail: ${String(e).slice(0, 90)}`);
      }
      if (++done % 5 === 0 || done === comms.length) console.log(`  ${done}/${comms.length} reports`);
    }
  }
  await Promise.all(Array.from({ length: Math.min(CONC, 6) }, work));
}

async function main() {
  if (!process.env.DEEPSEEK_API_KEY && process.env.DSKEY_FILE) {
    process.env.DEEPSEEK_API_KEY = (await fs.readFile(process.env.DSKEY_FILE, "utf8")).trim();
  }
  const llm = createLLM();
  if (!llm) { console.error("No LLM key (DEEPSEEK_API_KEY / DSKEY_FILE)."); process.exit(2); }

  const docs = await collect();
  const chars = docs.reduce((a, d) => a + d.text.length, 0);
  console.log(`provider=${llm.provider} episodes=${docs.length} chars=${chars} ~chunks=${Math.ceil(chars / CHUNK)}`);

  // ── concurrent LightRAG extraction ──
  const base = lightRagExtractor(llm, { gleanings: GLEAN });
  const texts = [];
  const seen = new Set();
  for (const d of docs) for (const ch of chunkDocument(d.text, { size: CHUNK, overlap: 120 })) {
    if (!seen.has(ch.text)) { seen.add(ch.text); texts.push(ch.text); }
  }
  console.log(`pre-extracting ${texts.length} chunks · concurrency ${CONC}…`);
  const cache = new Map();
  let i = 0, done = 0, fails = 0;
  const t0 = Date.now();
  async function worker() {
    while (i < texts.length) {
      const k = i++;
      try { cache.set(texts[k], await base.extract(texts[k])); }
      catch (e) { fails++; cache.set(texts[k], { entities: [], relations: [] }); }
      if (++done % 10 === 0 || done === texts.length) {
        const rate = done / ((Date.now() - t0) / 1000);
        console.log(`  ${done}/${texts.length} · ${rate.toFixed(1)}/s · ETA ${((texts.length - done) / rate / 60).toFixed(1)}m · fails ${fails}`);
      }
    }
  }
  await Promise.all(Array.from({ length: CONC }, worker));
  const extractor = { name: base.name, async extract(text) { return cache.get(text) ?? { entities: [], relations: [] }; } };

  console.log("assembling graph…");
  const { state, meta } = await buildGraph({
    graphId: GID, name: "Podcasts — LightRAG", language: "ru",
    documents: docs, extractor, chunkSize: CHUNK, chunkOverlap: 120, resolution: 1.2,
  });

  await addCommunityReports(state, llm);

  await fs.mkdir(path.join(PROJECTS, PID), { recursive: true });
  await fs.writeFile(path.join(PROJECTS, PID, "meta.json"), JSON.stringify({
    id: PID, name: "Podcasts (LightRAG + MS-GraphRAG)", createdAt: now,
    parse: { format: "plain", chunkSize: CHUNK, chunkOverlap: 120, perMessage: false },
    source: "data/podcast (full transcripts)", documentCount: docs.length,
  }, null, 2));
  await fs.writeFile(path.join(PROJECTS, PID, "documents.json"), JSON.stringify(
    docs.map((d) => ({ id: d.id, uri: d.uri, text: d.text, validFrom: null })), null, 2));

  const fullMeta = { ...meta, projectId: PID, scenario: { id: "themes", title: "Тематические сообщества знаний", communities: true, axis: "tx" } };
  await fs.mkdir(path.join(GRAPHS, GID), { recursive: true });
  await fs.writeFile(path.join(GRAPHS, GID, "base.json"), JSON.stringify({ nodes: state.nodes, edges: state.edges, journal: [] }, null, 2));
  await fs.writeFile(path.join(GRAPHS, GID, "journal.jsonl"), "");
  await fs.writeFile(path.join(GRAPHS, GID, "meta.json"), JSON.stringify(fullMeta, null, 2));
  await fs.writeFile(path.join(GRAPHS, GID, "schema.json"), JSON.stringify(deriveSchema(state), null, 2));

  const kinds = {};
  for (const n of state.nodes) if (n.layer === "entity") kinds[n.type] = (kinds[n.type] ?? 0) + 1;
  const comms = state.nodes.filter((n) => n.layer === "community");
  console.log(`DONE ${GID}: ${state.nodes.length} nodes, ${state.edges.length} edges, ${comms.length} communities (named), ${fails} extract fails`);
  console.log("sample communities:", comms.slice(0, 8).map((c) => c.name).join(" | "));
  console.log("entity kinds:", JSON.stringify(kinds));
}
main().catch((e) => { console.error(e); process.exit(1); });
