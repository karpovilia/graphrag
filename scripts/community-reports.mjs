/** MS-GraphRAG community reports for an EXISTING graph: (re)generate
 *  interpretable community names + summaries in the requested language.
 *
 *  NODE_USE_ENV_PROXY=1 DSKEY_FILE=/tmp/dskey GRAPH=podcast-graph LANG=en \
 *    node scripts/community-reports.mjs
 */
import { promises as fs } from "node:fs";
import path from "node:path";
import { createLLM, extractJson } from "/home/ki/repos/graphcraft/packages/graph-core/dist/index.js";

const GRAPHS = "/home/ki/repos/graphcraft/graphs";
const GID = process.env.GRAPH;
const LANG = (process.env.LANG_OUT ?? process.env.LANG ?? "en").startsWith("ru") ? "Russian" : "English";
const CONC = Number(process.env.CONC ?? "6");
if (!GID) { console.error("set GRAPH=<id>"); process.exit(2); }

const SYS = `You write MS-GraphRAG community reports. Given a cluster of related entities and their relationships from a knowledge graph, return JSON {"title":"...","summary":"..."}. Title: a short, specific, human-readable theme name (3-7 words). Summary: 2-3 sentences on what the community is about and how its members relate. Write BOTH in ${LANG}. Return ONLY the JSON.`;

async function main() {
  if (!process.env.DEEPSEEK_API_KEY && process.env.DSKEY_FILE) {
    process.env.DEEPSEEK_API_KEY = (await fs.readFile(process.env.DSKEY_FILE, "utf8")).trim();
  }
  const llm = createLLM();
  if (!llm) { console.error("No LLM key."); process.exit(2); }

  const base = JSON.parse(await fs.readFile(path.join(GRAPHS, GID, "base.json"), "utf8"));
  const byId = new Map(base.nodes.map((n) => [n.id, n]));
  const comms = base.nodes.filter((n) => n.layer === "community");
  const members = new Map();
  for (const e of base.edges) if (e.type === "member_of") {
    (members.get(e.targetId) ?? members.set(e.targetId, []).get(e.targetId)).push(e.sourceId);
  }
  console.log(`graph=${GID} lang=${LANG} communities=${comms.length} · concurrency ${CONC}`);

  let i = 0, done = 0;
  async function work() {
    while (i < comms.length) {
      const c = comms[i++];
      const ids = new Set(members.get(c.id) ?? []);
      const ents = [...ids].map((id) => byId.get(id)).filter(Boolean);
      const entLines = ents.slice(0, 40).map((m) => `- ${m.name} (${m.type})${m.summary ? ": " + m.summary : ""}`).join("\n");
      const relLines = base.edges
        .filter((e) => e.type === "entity_relation" && ids.has(e.sourceId) && ids.has(e.targetId))
        .slice(0, 40).map((e) => `- ${byId.get(e.sourceId)?.name} → ${byId.get(e.targetId)?.name}${e.relation ? " (" + e.relation + ")" : ""}`).join("\n");
      try {
        const { text } = await llm.complete(
          [{ role: "system", content: SYS }, { role: "user", content: `Entities:\n${entLines}\n\nRelationships:\n${relLines || "(none)"}` }],
          { temperature: 0.2, maxTokens: 320, jsonObject: true });
        const j = extractJson(text);
        if (j && typeof j === "object") {
          if (j.title) c.name = String(j.title).slice(0, 80);
          if (j.summary) c.summary = String(j.summary);
          c.attributes = { ...c.attributes, report: true };
        }
      } catch (e) { console.log(`  fail: ${String(e).slice(0, 90)}`); }
      if (++done % 10 === 0 || done === comms.length) console.log(`  ${done}/${comms.length}`);
    }
  }
  await Promise.all(Array.from({ length: CONC }, work));

  await fs.writeFile(path.join(GRAPHS, GID, "base.json"), JSON.stringify({ nodes: base.nodes, edges: base.edges, journal: base.journal ?? [] }, null, 2));
  console.log("samples:", comms.slice(0, 8).map((c) => c.name).join(" | "));
  console.log("DONE");
}
main().catch((e) => { console.error(e); process.exit(1); });
