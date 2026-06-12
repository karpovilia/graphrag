import { describe, it, expect } from "vitest";
import { dedupCandidates } from "./dedup.js";
import { orphanRescuer } from "./orphans.js";
import { godNodes, surpriseEdges } from "./anomalies.js";
import { makeNode, makeEdge, makeState } from "../test-helpers.js";

describe("dedup agent", () => {
  it("proposes a merge for near-duplicate names sharing neighbours", () => {
    const state = makeState({
      nodes: [
        makeNode({ id: "a", name: "Хаббл", type: "PERSON" }),
        makeNode({ id: "b", name: "Хаббл, Эдвин", type: "PERSON" }),
        makeNode({ id: "c", name: "Астрономия", type: "CONCEPT" }),
      ],
      edges: [
        makeEdge({ sourceId: "a", targetId: "c" }),
        makeEdge({ sourceId: "b", targetId: "c" }),
      ],
    });
    const sugg = dedupCandidates(state);
    expect(sugg.length).toBeGreaterThan(0);
    expect(sugg[0]!.action).toBe("merge");
    expect(sugg[0]!.targetNodeIds.sort()).toEqual(["a", "b"]);
  });

  it("skips pinned nodes", () => {
    const state = makeState({
      nodes: [
        makeNode({ id: "a", name: "Хаббл", pinned: true }),
        makeNode({ id: "b", name: "Хаббл, Эдвин" }),
      ],
    });
    expect(dedupCandidates(state)).toHaveLength(0);
  });
});

describe("orphan rescuer", () => {
  it("flags isolated entity nodes", () => {
    const state = makeState({
      nodes: [makeNode({ id: "lonely" }), makeNode({ id: "x" }), makeNode({ id: "y" })],
      edges: [makeEdge({ sourceId: "x", targetId: "y" })],
    });
    const sugg = orphanRescuer(state);
    expect(sugg.map((s) => s.targetNodeIds[0])).toEqual(["lonely"]);
    expect(sugg[0]!.action).toBe("delete");
  });
});

describe("anomalies", () => {
  it("godNodes ranks by degree", () => {
    const state = makeState({
      nodes: [makeNode({ id: "hub" }), makeNode({ id: "a" }), makeNode({ id: "b" })],
      edges: [
        makeEdge({ sourceId: "hub", targetId: "a" }),
        makeEdge({ sourceId: "hub", targetId: "b" }),
        makeEdge({ sourceId: "a", targetId: "b" }),
      ],
    });
    const gods = godNodes(state, { topN: 1 });
    expect(gods[0]!.id).toBe("hub");
    expect(gods[0]!.degree).toBe(2);
  });

  it("surpriseEdges ranks cross-community + high-confidence edges", () => {
    const state = makeState({
      nodes: [
        makeNode({ id: "n1" }),
        makeNode({ id: "n2" }),
        makeNode({ id: "c1", layer: "community" }),
        makeNode({ id: "c2", layer: "community" }),
      ],
      edges: [
        makeEdge({ type: "member_of", sourceId: "n1", targetId: "c1" }),
        makeEdge({ type: "member_of", sourceId: "n2", targetId: "c2" }),
        makeEdge({ id: "cross", sourceId: "n1", targetId: "n2", confidence: "ambiguous" }),
      ],
    });
    const s = surpriseEdges(state, { topN: 5 });
    expect(s[0]!.edgeId).toBe("cross");
    expect(s[0]!.fromCommunity).toBe("c1");
    expect(s[0]!.toCommunity).toBe("c2");
  });
});
