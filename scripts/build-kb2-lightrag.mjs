/** kb2 → LightRAG knowledge graph. Plain-JS (.mjs) twin of build-kb2-lightrag.ts,
 *  importing @graphcraft/core from its built dist so it runs under plain `node`
 *  (the sandbox blocks node's TS loader / tsx, but plain JS is fine).
 *
 *  NODE_USE_ENV_PROXY=1 DSKEY_FILE=/tmp/dskey WEEKS=16 node scripts/build-kb2-lightrag.mjs
 */
import { promises as fs } from "node:fs";
import path from "node:path";
import {
  buildGraph, chunkDocument, createLLM, deriveSchema, lightRagExtractor, nowIso,
} from "/home/ki/repos/graphcraft/packages/graph-core/dist/index.js";

const ROOT = "/home/ki/repos/kb2/dump";
const PROJECTS = "/home/ki/repos/graphcraft/projects";
const GRAPHS = "/home/ki/repos/graphcraft/graphs";

const WEEKS = Number(process.env.WEEKS ?? "0");
const MODE = process.env.MODE ?? "summary";
const CHUNK = Number(process.env.CHUNK ?? "2400");
const GLEAN = Number(process.env.GLEAN ?? "1");
const LIMIT = Number(process.env.LIMIT ?? "0");
const CONC = Number(process.env.CONC ?? "8");
const PID = process.env.KB2_PID ?? "kb2-lrag";
const GID = process.env.KB2_GID ?? "kb2-lrag-graph";
const now = nowIso();

const HEAD = /^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})\s+(.+?)\s*$/;

function toSummary(body) {
  const i = body.search(/^\s*Transcript:/im);
  return (i >= 0 ? body.slice(0, i) : body).replace(/^\s*text:\s*/i, "").trim();
}

async function collect() {
  let weeks = (await fs.readdir(ROOT)).filter((w) => /^20\d\d-W\d\d$/.test(w)).sort();
  if (WEEKS > 0) weeks = weeks.slice(-WEEKS);
  const docs = [];
  const walk = async (dir) => {
    for (const e of await fs.readdir(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) await walk(p);
      else if (e.name.endsWith(".txt")) {
        const raw = await fs.readFile(p, "utf8");
        const lines = raw.split(/\r?\n/);
        const m = lines[0]?.match(HEAD);
        const validFrom = m ? `${m[1]}T${m[2]}.000Z` : null;
        const title = m ? m[3] : e.name;
        const body = m ? lines.slice(1).join("\n") : raw;
        const text = MODE === "summary" ? toSummary(body) : body.replace(/^\s*text:\s*/i, "").trim();
        if (text.length > 40) docs.push({ id: path.relative(ROOT, p), uri: title, text, validFrom });
      }
    }
  };
  for (const w of weeks) await walk(path.join(ROOT, w));
  return LIMIT > 0 ? docs.slice(0, LIMIT) : docs;
}

async function main() {
  if (!process.env.DEEPSEEK_API_KEY && process.env.DSKEY_FILE) {
    process.env.DEEPSEEK_API_KEY = (await fs.readFile(process.env.DSKEY_FILE, "utf8")).trim();
  }
  const llm = createLLM();
  if (!llm) {
    console.error("No LLM key. Set DEEPSEEK_API_KEY (or DSKEY_FILE) and retry.");
    process.exit(2);
  }
  const docs = await collect();
  const chars = docs.reduce((a, d) => a + d.text.length, 0);
  console.log(`provider=${llm.provider} mode=${MODE} weeks=${WEEKS || "all"} files=${docs.length} chars=${chars} ~chunks=${Math.ceil(chars / CHUNK)}`);

  const base = lightRagExtractor(llm, { gleanings: GLEAN });

  // ── pre-extract every unique chunk CONCURRENTLY (the LLM phase is the cost) ──
  // buildGraph re-chunks with the same size/overlap → identical texts → cache hits.
  const texts = [];
  const seen = new Set();
  for (const d of docs) {
    for (const ch of chunkDocument(d.text, { size: CHUNK, overlap: 120 })) {
      if (!seen.has(ch.text)) { seen.add(ch.text); texts.push(ch.text); }
    }
  }
  console.log(`pre-extracting ${texts.length} unique chunks · concurrency ${CONC}…`);
  const cache = new Map();
  let done = 0, fails = 0;
  const t0 = Date.now();
  let next = 0;
  async function worker() {
    while (next < texts.length) {
      const i = next++;
      const text = texts[i];
      try {
        cache.set(text, await base.extract(text));
      } catch (e) {
        fails++;
        cache.set(text, { entities: [], relations: [] });
        if (fails <= 5) console.log(`  extract fail #${fails}: ${String(e).slice(0, 100)}`);
      }
      if (++done % 25 === 0 || done === texts.length) {
        const rate = done / ((Date.now() - t0) / 1000);
        const eta = ((texts.length - done) / rate / 60).toFixed(1);
        console.log(`  ${done}/${texts.length} · ${rate.toFixed(1)}/s · ETA ${eta}m · fails ${fails}`);
      }
    }
  }
  await Promise.all(Array.from({ length: CONC }, worker));
  console.log(`extraction done in ${((Date.now() - t0) / 60000).toFixed(1)}m · ${fails} fails`);

  const extractor = {
    name: base.name,
    async extract(text) { return cache.get(text) ?? { entities: [], relations: [] }; },
  };

  console.log("assembling graph…");
  const { state, meta } = await buildGraph({
    graphId: GID, name: "KB2 — LightRAG", language: "ru",
    documents: docs, extractor, chunkSize: CHUNK, chunkOverlap: 120, resolution: 1.2,
  });

  await fs.mkdir(path.join(PROJECTS, PID), { recursive: true });
  await fs.writeFile(path.join(PROJECTS, PID, "meta.json"), JSON.stringify({
    id: PID, name: "KB2 (LightRAG)", createdAt: now,
    parse: { format: "plain", chunkSize: CHUNK, chunkOverlap: 120, perMessage: false },
    source: `kb2/dump (${MODE}, ${WEEKS || "all"} weeks)`, documentCount: docs.length,
  }, null, 2));
  await fs.writeFile(path.join(PROJECTS, PID, "documents.json"), JSON.stringify(
    docs.map((d) => ({ id: d.id, uri: d.uri, text: d.text, validFrom: d.validFrom ?? null })), null, 2));

  const fullMeta = { ...meta, projectId: PID, scenario: { id: "themes", title: "Тематические сообщества знаний", communities: true, axis: "tx" } };
  await fs.mkdir(path.join(GRAPHS, GID), { recursive: true });
  await fs.writeFile(path.join(GRAPHS, GID, "base.json"), JSON.stringify({ nodes: state.nodes, edges: state.edges, journal: [] }, null, 2));
  await fs.writeFile(path.join(GRAPHS, GID, "journal.jsonl"), "");
  await fs.writeFile(path.join(GRAPHS, GID, "meta.json"), JSON.stringify(fullMeta, null, 2));
  await fs.writeFile(path.join(GRAPHS, GID, "schema.json"), JSON.stringify(deriveSchema(state), null, 2));

  const kinds = {};
  for (const n of state.nodes) if (n.layer === "entity") kinds[n.type] = (kinds[n.type] ?? 0) + 1;
  const comms = state.nodes.filter((n) => n.layer === "community").length;
  console.log(`DONE ${GID}: ${state.nodes.length} nodes, ${state.edges.length} edges, ${comms} communities, ${fails} extract fails`);
  console.log("entity kinds:", JSON.stringify(kinds));
}
main().catch((e) => { console.error(e); process.exit(1); });
