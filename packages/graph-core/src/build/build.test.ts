import { describe, it, expect } from "vitest";
import { chunkDocument } from "./chunk.js";
import { louvain } from "./louvain.js";
import { buildGraph } from "./pipeline.js";
import { heuristicExtract, llmExtractor, type Extractor } from "./extract.js";
import { lightRagExtractor } from "./lightrag.js";
import type { CompletionClient } from "../llm/base.js";

describe("chunkDocument", () => {
  it("windows text with overlap and skips blank tails", () => {
    const chunks = chunkDocument("abcdefghij", { size: 4, overlap: 1 });
    // step = size - overlap = 3 → 0-4, 3-7, 6-10 (end reaches n, stops)
    expect(chunks.map((c) => c.text)).toEqual(["abcd", "defg", "ghij"]);
    expect(chunks[0]).toMatchObject({ start: 0, end: 4 });
  });
  it("clamps overlap ≥ size to 0", () => {
    expect(chunkDocument("abcdef", { size: 3, overlap: 5 }).map((c) => c.text)).toEqual(["abc", "def"]);
  });
});

describe("louvain", () => {
  it("separates two obvious clusters", () => {
    // triangle {a,b,c} and triangle {x,y,z} joined by one weak bridge
    const edges = [
      { a: "a", b: "b", w: 5 }, { a: "b", b: "c", w: 5 }, { a: "a", b: "c", w: 5 },
      { a: "x", b: "y", w: 5 }, { a: "y", b: "z", w: 5 }, { a: "x", b: "z", w: 5 },
      { a: "c", b: "x", w: 1 },
    ];
    const m = louvain(["a", "b", "c", "x", "y", "z"], edges);
    expect(m.get("a")).toBe(m.get("b"));
    expect(m.get("b")).toBe(m.get("c"));
    expect(m.get("x")).toBe(m.get("y"));
    expect(m.get("y")).toBe(m.get("z"));
    expect(m.get("a")).not.toBe(m.get("x"));
  });
});

describe("heuristicExtract", () => {
  it("pulls capitalised name runs, drops stopwords", () => {
    const out = heuristicExtract("Иван Чепиков работает в Высшая Школа Экономики. Это тест.");
    const names = out.entities.map((e) => e.name);
    expect(names).toContain("Иван Чепиков");
    expect(names).toContain("Высшая Школа Экономики");
    expect(names).not.toContain("Это");
    expect(out.relations).toHaveLength(0);
  });
});

describe("buildGraph — keyless heuristic pipeline", () => {
  it("produces chunk + entity + community layers with the right edges", async () => {
    const text =
      "Иван Чепиков работает в ВШЭ. ВШЭ находится в Москве. " +
      "Эдвин Хаббл наблюдал Галактику в Телескоп Хаббл. Галактику изучал Эдвин Хаббл.";
    const { state, meta } = await buildGraph({
      graphId: "t",
      name: "Test",
      documents: [{ id: "d1", uri: "doc1.txt", text }],
      chunkSize: 80,
      chunkOverlap: 0,
      now: "2026-01-01T00:00:00.000Z",
      layout: false,
    });

    const layers = new Set(state.nodes.map((n) => n.layer));
    expect(layers.has("chunk")).toBe(true);
    expect(layers.has("entity")).toBe(true);

    const types = new Set(state.edges.map((e) => e.type));
    expect(types.has("mentioned_in")).toBe(true);
    expect(types.has("entity_relation")).toBe(true);

    // co-occurrence edges are inferred, not extracted
    const rel = state.edges.find((e) => e.type === "entity_relation");
    expect(rel?.relation).toBe("co_occurrence");
    expect(rel?.confidence).toBe("inferred");

    expect(meta.source).toBe("build:heuristic");
    expect(meta.nodeCount).toBe(state.nodes.length);
    // deterministic ids → stable build
    expect(state.nodes.every((n) => n.txFrom === "2026-01-01T00:00:00.000Z")).toBe(true);
  });
});

describe("lightRagExtractor — typed entities + relations with strength", () => {
  it("maps LightRAG JSON (open types, keywords, strength) into ChunkExtraction", async () => {
    const fake: CompletionClient = {
      provider: "fake",
      complete: async () =>
        ({
          text: JSON.stringify({
            entities: [
              { name: "Илья Карпов", type: "person", description: "lead" },
              { name: "Voxys", type: "organization", description: "company" },
            ],
            relationships: [
              { source: "Илья Карпов", target: "Voxys", keywords: "works at", description: "lead at Voxys", strength: 9 },
            ],
          }),
        }),
    };
    const out = await lightRagExtractor(fake).extract("…");
    expect(out.entities.map((e) => [e.name, e.type])).toEqual([["Илья Карпов", "PERSON"], ["Voxys", "ORGANIZATION"]]);
    expect(out.relations[0]).toMatchObject({ source: "Илья Карпов", target: "Voxys", predicate: "works at", weight: 9 });
  });
  it("drops relationships whose endpoints aren't extracted entities", async () => {
    const fake: CompletionClient = {
      provider: "fake",
      complete: async () => ({ text: JSON.stringify({ entities: [{ name: "A", type: "x" }], relationships: [{ source: "A", target: "Ghost", strength: 5 }] }) }),
    };
    const out = await lightRagExtractor(fake).extract("…");
    expect(out.relations).toHaveLength(0);
  });
});

describe("buildGraph — LLM pipeline with a fake client", () => {
  it("uses extracted entities + explicit relations (not co-occurrence)", async () => {
    const fake: CompletionClient = {
      provider: "fake",
      complete: async () =>
        ({
          text: JSON.stringify({
            entities: [
              { name: "Hubble", type: "PERSON", description: "astronomer" },
              { name: "Galaxy", type: "CONCEPT", description: "a galaxy" },
            ],
            relations: [{ source: "Hubble", target: "Galaxy", predicate: "studied", weight: 3 }],
          }),
        }),
    };
    const ext: Extractor = llmExtractor(fake);
    const { state } = await buildGraph({
      graphId: "t2",
      documents: [{ id: "d", text: "Hubble studied the Galaxy at length." }],
      extractor: ext,
      now: "2026-01-01T00:00:00.000Z",
      layout: false,
    });

    const ent = state.nodes.filter((n) => n.layer === "entity");
    expect(ent.map((e) => e.name).sort()).toEqual(["Galaxy", "Hubble"]);
    expect(ent.find((e) => e.name === "Hubble")?.type).toBe("PERSON");

    const rel = state.edges.find((e) => e.type === "entity_relation");
    expect(rel?.relation).toBe("studied");
    expect(rel?.confidence).toBe("extracted");
    expect((rel?.attributes as { rawWeight?: number }).rawWeight).toBe(3);
  });

  it("registers emergent layers the extractor proposes and assigns them", async () => {
    const fake: CompletionClient = {
      provider: "fake",
      complete: async () =>
        ({
          text: JSON.stringify({
            entities: [
              { name: "Анна", type: "PERSON", layer: "person" },
              { name: "Выручка Q1", type: "CONCEPT", layer: "metric" },
            ],
            relations: [],
          }),
        }),
    };
    const { state, meta } = await buildGraph({
      graphId: "t3",
      documents: [{ id: "d", text: "Анна отвечает за Выручка Q1." }],
      extractor: llmExtractor(fake),
      now: "2026-01-01T00:00:00.000Z",
      layout: false,
    });

    const anna = state.nodes.find((n) => n.name === "Анна");
    expect(anna?.layer).toBe("person");
    expect(anna?.granularity).toBe(1); // emergent strata sit at entity level
    const names = (meta.layers ?? []).map((l) => l.name).sort();
    expect(names).toEqual(["metric", "person"]);
    expect((meta.layers ?? []).every((l) => l.emergent)).toBe(true);
    expect(meta.layersPresent).toContain("person");
  });
});
