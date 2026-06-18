/** Build a knowledge graph from raw text and write it to graphs/<id>/.
 *
 *  Usage:
 *    pnpm build:graph <file-or-dir> [--id ID] [--name "Name"] [--lang ru]
 *                     [--llm] [--chunk-size 1200] [--overlap 100]
 *
 *  Reads a single .txt/.md file or every text file in a directory (one
 *  document each). Extraction is keyless by default (heuristic); pass --llm
 *  to use the configured LLM provider (DEEPSEEK_API_KEY etc., see .env.example).
 */
import { promises as fs } from "node:fs";
import path from "node:path";
import {
  buildGraph,
  createLLM,
  heuristicExtractor,
  lightRagExtractor,
  type BuildDocument,
} from "@graphcraft/core";

const GRAPHS_DIR = process.env.GRAPHS_DIR ?? "./graphs";
const TEXT_EXT = new Set([".txt", ".md", ".markdown", ".text"]);

function arg(name: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : undefined;
}
const has = (name: string) => process.argv.includes(`--${name}`);

async function collectDocs(input: string): Promise<BuildDocument[]> {
  const stat = await fs.stat(input);
  if (stat.isFile()) {
    return [{ id: path.basename(input), uri: input, text: await fs.readFile(input, "utf8") }];
  }
  const out: BuildDocument[] = [];
  const walk = async (dir: string) => {
    for (const ent of await fs.readdir(dir, { withFileTypes: true })) {
      const p = path.join(dir, ent.name);
      if (ent.isDirectory()) await walk(p);
      else if (TEXT_EXT.has(path.extname(ent.name).toLowerCase())) {
        out.push({ id: path.relative(input, p), uri: p, text: await fs.readFile(p, "utf8") });
      }
    }
  };
  await walk(input);
  return out;
}

async function main() {
  const input = process.argv[2];
  if (!input || input.startsWith("--")) {
    console.error("usage: pnpm build:graph <file-or-dir> [--id ID] [--name N] [--lang ru] [--llm] [--chunk-size N] [--overlap N]");
    process.exit(1);
  }
  const id = arg("id") ?? (path.basename(input).replace(/\.[^.]+$/, "") || "built");

  const documents = await collectDocs(input);
  if (!documents.length) {
    console.error(`no text documents found at ${input}`);
    process.exit(1);
  }

  let extractor = heuristicExtractor;
  if (has("llm")) {
    const llm = createLLM();
    if (llm) {
      extractor = lightRagExtractor(llm, { gleanings: 1 });
      console.log(`using LLM provider: ${llm.provider}`);
    } else {
      console.warn("--llm requested but no provider configured (set DEEPSEEK_API_KEY etc.); falling back to heuristic");
    }
  }

  console.log(`building '${id}' from ${documents.length} document(s) with ${extractor.name}…`);
  const { state, meta } = await buildGraph({
    graphId: id,
    name: arg("name") ?? id,
    language: arg("lang"),
    documents,
    extractor,
    chunkSize: arg("chunk-size") ? Number(arg("chunk-size")) : undefined,
    chunkOverlap: arg("overlap") ? Number(arg("overlap")) : undefined,
  });

  const dir = path.join(GRAPHS_DIR, id);
  await fs.mkdir(dir, { recursive: true });
  await fs.writeFile(
    path.join(dir, "base.json"),
    JSON.stringify({ nodes: state.nodes, edges: state.edges, journal: [] }, null, 2),
  );
  await fs.writeFile(path.join(dir, "journal.jsonl"), "");
  await fs.writeFile(path.join(dir, "meta.json"), JSON.stringify(meta, null, 2));

  const layers = meta.layersPresent.join(", ");
  console.log(`wrote ${dir} — ${state.nodes.length} nodes, ${state.edges.length} edges (layers: ${layers})`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
