/** Build a real LightRAG knowledge graph over the kb2 meeting-transcript dump.
 *  Needs an LLM key (DEEPSEEK_API_KEY or the generic LLM_* vars) — LightRAG
 *  calls the model per chunk. Scope it with env vars so a run stays sane:
 *
 *    WEEKS=12          # most-recent N week folders (default: all 67)
 *    MODE=summary|full # summary+action-items only (default) or whole transcript
 *    CHUNK=2400        # chunk size (chars)
 *    GLEAN=1           # LightRAG gleaning passes
 *    LIMIT=0           # cap number of files (0 = no cap)
 *    PID=kb2-lrag GID=kb2-lrag-graph
 *
 *  DEEPSEEK_API_KEY=sk-... WEEKS=12 npx tsx scripts/build-kb2-lightrag.ts
 */
import { promises as fs } from "node:fs";
import path from "node:path";
import {
  buildGraph, createLLM, deriveSchema, lightRagExtractor, nowIso,
  type BuildDocument, type Extractor, type GraphMeta,
} from "@graphcraft/core";

const ROOT = "/home/ki/repos/kb2/dump";
const PROJECTS = "/home/ki/repos/graphcraft/projects";
const GRAPHS = "/home/ki/repos/graphcraft/graphs";

const WEEKS = Number(process.env.WEEKS ?? "0");           // 0 = all
const MODE = (process.env.MODE ?? "summary") as "summary" | "full";
const CHUNK = Number(process.env.CHUNK ?? "2400");
const GLEAN = Number(process.env.GLEAN ?? "1");
const LIMIT = Number(process.env.LIMIT ?? "0");           // 0 = no cap
const PID = process.env.PID ?? "kb2-lrag";
const GID = process.env.GID ?? "kb2-lrag-graph";
const now = nowIso();

const HEAD = /^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})\s+(.+?)\s*$/;

/** Keep Summary + Action items, drop the raw Transcript (high signal, small). */
function toSummary(body: string): string {
  const i = body.search(/^\s*Transcript:/im);
  return (i >= 0 ? body.slice(0, i) : body).replace(/^\s*text:\s*/i, "").trim();
}

async function collect(): Promise<BuildDocument[]> {
  let weeks = (await fs.readdir(ROOT)).filter((w) => /^20\d\d-W\d\d$/.test(w)).sort();
  if (WEEKS > 0) weeks = weeks.slice(-WEEKS);
  const docs: BuildDocument[] = [];
  const walk = async (dir: string) => {
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
  // allow the key via a file path (avoids shell $(...) substitution under the sandbox)
  if (!process.env.DEEPSEEK_API_KEY && process.env.DSKEY_FILE) {
    process.env.DEEPSEEK_API_KEY = (await fs.readFile(process.env.DSKEY_FILE, "utf8")).trim();
  }
  const llm = createLLM();
  if (!llm) {
    console.error("No LLM key. Set DEEPSEEK_API_KEY (or LLM_API_KEY + LLM_BASE_URL) and retry.");
    process.exit(2);
  }
  const docs = await collect();
  const chars = docs.reduce((a, d) => a + d.text.length, 0);
  console.log(`provider=${llm.provider} mode=${MODE} weeks=${WEEKS || "all"} files=${docs.length} chars=${chars} ~chunks=${Math.ceil(chars / CHUNK)}`);

  // progress-logging LightRAG extractor
  const base = lightRagExtractor(llm, { gleanings: GLEAN });
  let done = 0;
  const t0 = Date.now();
  const extractor: Extractor = {
    name: base.name,
    async extract(text) {
      const r = await base.extract(text);
      if (++done % 20 === 0) {
        const rate = done / ((Date.now() - t0) / 1000);
        console.log(`  ${done} chunks · ${rate.toFixed(2)}/s`);
      }
      return r;
    },
  };

  console.log("building (this calls the LLM per chunk — be patient)…");
  const { state, meta } = await buildGraph({
    graphId: GID, name: "KB2 — LightRAG", language: "ru",
    documents: docs, extractor, chunkSize: CHUNK, chunkOverlap: 120, resolution: 1.2,
  });

  // persist project + graph in the hub's on-disk layout
  await fs.mkdir(path.join(PROJECTS, PID), { recursive: true });
  await fs.writeFile(path.join(PROJECTS, PID, "meta.json"), JSON.stringify({
    id: PID, name: "KB2 (LightRAG)", createdAt: now,
    parse: { format: "plain", chunkSize: CHUNK, chunkOverlap: 120, perMessage: false },
    source: `kb2/dump (${MODE}, ${WEEKS || "all"} weeks)`, documentCount: docs.length,
  }, null, 2));
  await fs.writeFile(path.join(PROJECTS, PID, "documents.json"), JSON.stringify(
    docs.map((d) => ({ id: d.id, uri: d.uri, text: d.text, validFrom: d.validFrom ?? null })), null, 2));

  const fullMeta: GraphMeta = {
    ...meta, projectId: PID,
    scenario: { id: "themes", title: "Тематические сообщества знаний", communities: true, axis: "tx" },
  };
  await fs.mkdir(path.join(GRAPHS, GID), { recursive: true });
  await fs.writeFile(path.join(GRAPHS, GID, "base.json"), JSON.stringify({ nodes: state.nodes, edges: state.edges, journal: [] }, null, 2));
  await fs.writeFile(path.join(GRAPHS, GID, "journal.jsonl"), "");
  await fs.writeFile(path.join(GRAPHS, GID, "meta.json"), JSON.stringify(fullMeta, null, 2));
  await fs.writeFile(path.join(GRAPHS, GID, "schema.json"), JSON.stringify(deriveSchema(state), null, 2));

  const kinds: Record<string, number> = {};
  for (const n of state.nodes) if (n.layer === "entity") kinds[n.type] = (kinds[n.type] ?? 0) + 1;
  const comms = state.nodes.filter((n) => n.layer === "community").length;
  console.log(`DONE ${GID}: ${state.nodes.length} nodes, ${state.edges.length} edges, ${comms} communities`);
  console.log("entity kinds:", JSON.stringify(kinds));
}
main().catch((e) => { console.error(e); process.exit(1); });
