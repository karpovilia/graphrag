/** Generate a small synthetic graph with deliberate curation targets:
 *  duplicate entities, an orphan, two communities, and a cross-community
 *  inferred edge. Writes graphs/<id>/{base.json,journal.jsonl,meta.json}.
 *
 *  Usage: pnpm gen:sample [graphId]
 */
import { promises as fs } from "node:fs";
import path from "node:path";
import {
  LAYER_GRANULARITY,
  nowIso,
  withLayout,
  type Edge,
  type GraphMeta,
  type GraphState,
  type Node,
  type Layer,
} from "@graphcraft/core";

const GRAPHS_DIR = process.env.GRAPHS_DIR ?? "./graphs";
const id = process.argv[2] ?? "sample";
const now = nowIso();

let e = 0;
const node = (
  nid: string,
  name: string,
  layer: Layer,
  type: string,
): Node => ({
  id: nid,
  graphId: id,
  layer,
  type,
  granularity: LAYER_GRANULARITY[layer],
  name,
  summary: null,
  attributes: {},
  provenance: [],
  x: null,
  y: null,
  pinned: false,
  validFrom: null,
  validTo: null,
  txFrom: now,
  txTo: null,
});

const edge = (
  src: string,
  tgt: string,
  type: Edge["type"],
  relation: string | null = null,
  confidence: Edge["confidence"] = "extracted",
): Edge => ({
  id: `e${++e}`,
  graphId: id,
  type,
  sourceId: src,
  targetId: tgt,
  weight: 1,
  relation,
  explanation: null,
  confidence,
  provenance: [],
  attributes: {},
  validFrom: null,
  validTo: null,
  txFrom: now,
  txTo: null,
  invalidation: null,
});

const nodes: Node[] = [
  node("c_astro", "Астрономия", "community", "COMMUNITY"),
  node("c_edu", "Образование", "community", "COMMUNITY"),
  node("hubble1", "Хаббл", "entity", "PERSON"),
  node("hubble2", "Хаббл, Эдвин", "entity", "PERSON"), // dup of hubble1
  node("telescope", "Телескоп Хаббл", "entity", "OBJECT"),
  node("galaxy", "Галактика", "entity", "CONCEPT"),
  node("hse1", "ВШЭ", "entity", "ORG"),
  node("hse2", "Высшая школа экономики", "entity", "ORG"), // dup of hse1
  node("ivan", "Иван Чепиков", "entity", "PERSON"),
  node("vanya", "Ваня", "entity", "PERSON"), // dup of ivan
  node("orphan", "НеизвестныйУзел", "entity", "MISC"), // isolated
];

const edges: Edge[] = [
  edge("hubble1", "c_astro", "member_of"),
  edge("hubble2", "c_astro", "member_of"),
  edge("telescope", "c_astro", "member_of"),
  edge("galaxy", "c_astro", "member_of"),
  edge("hse1", "c_edu", "member_of"),
  edge("hse2", "c_edu", "member_of"),
  edge("ivan", "c_edu", "member_of"),
  edge("vanya", "c_edu", "member_of"),
  edge("hubble1", "telescope", "entity_relation", "наблюдал в"),
  edge("hubble2", "galaxy", "entity_relation", "изучал"),
  edge("telescope", "galaxy", "entity_relation", "снимал"),
  edge("ivan", "hse1", "entity_relation", "работает в"),
  edge("vanya", "hse2", "entity_relation", "работает в"),
  // cross-community, inferred — should surface as a "surprise" edge
  edge("ivan", "hubble1", "entity_relation", "читал про", "inferred"),
];

async function main() {
  let state: GraphState = { nodes, edges, journal: [] };
  state = withLayout(state, { seed: 42 });

  const meta: GraphMeta = {
    id,
    name: "Sample (synthetic)",
    language: "ru",
    version: 0,
    source: "gen-sample",
    createdAt: now,
    nodeCount: state.nodes.length,
    edgeCount: state.edges.length,
    layersPresent: ["entity", "community"],
  };

  const dir = path.join(GRAPHS_DIR, id);
  await fs.mkdir(dir, { recursive: true });
  await fs.writeFile(
    path.join(dir, "base.json"),
    JSON.stringify({ nodes: state.nodes, edges: state.edges, journal: [] }, null, 2),
  );
  await fs.writeFile(path.join(dir, "journal.jsonl"), "");
  await fs.writeFile(path.join(dir, "meta.json"), JSON.stringify(meta, null, 2));
  console.log(`wrote ${dir} (${state.nodes.length} nodes, ${state.edges.length} edges)`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
