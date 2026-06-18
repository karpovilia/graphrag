import { describe, it, expect } from "vitest";
import type { Edge, GraphMeta, GraphState, Node } from "@graphcraft/core";
import { renderGraph } from "./render.js";

const META: GraphMeta = {
  id: "g", name: "G", language: "en", version: 0,
  createdAt: "2020-01-01T00:00:00.000Z",
  nodeCount: 0, edgeCount: 0, layersPresent: [],
};

function node(p: Partial<Node> & { id: string }): Node {
  return {
    graphId: "g", layer: "entity", type: "PERSON", granularity: 1,
    name: p.id, attributes: {}, provenance: [],
    validFrom: null, validTo: null, txFrom: null, txTo: null,
    ...p,
  } as Node;
}
function edge(id: string, s: string, t: string, p: Partial<Edge> = {}): Edge {
  return {
    id, graphId: "g", type: "entity_relation", sourceId: s, targetId: t,
    weight: null, relation: null, explanation: null, confidence: "extracted",
    provenance: [], attributes: {},
    validFrom: null, validTo: null, txFrom: null, txTo: null, invalidation: null,
    ...p,
  } as Edge;
}

describe("renderGraph — layer filter", () => {
  const state: GraphState = {
    nodes: [
      node({ id: "c1", layer: "chunk" }),
      node({ id: "e1", layer: "entity" }),
      node({ id: "e2", layer: "entity" }),
    ],
    edges: [
      edge("mc", "e1", "c1", { type: "mentioned_in" }), // entity↔chunk
      edge("ee", "e1", "e2"), // entity↔entity
    ],
    journal: [],
  };

  it("chunks are NOT canvas nodes; entities detailed by type", () => {
    const r = renderGraph(state, META);
    // chunk node is excluded from the canvas (provenance only)
    expect(r.graph.nodes.map((n) => n.id).sort()).toEqual(["e1", "e2"]);
    expect(r.graph.legends.layers).toEqual([]); // no chunk chip
    const types = Object.fromEntries(r.graph.legends.types.map((t) => [t.type, t.count]));
    expect(types).toEqual({ PERSON: 2 });
  });

  it("filtering by entity kind keeps only that type", () => {
    const withOrg: GraphState = {
      nodes: [...state.nodes, node({ id: "o1", layer: "entity", type: "ORG" })],
      edges: state.edges,
      journal: [],
    };
    const r = renderGraph(withOrg, META, { types: ["PERSON"] });
    expect(r.graph.nodes.map((n) => n.id).sort()).toEqual(["e1", "e2"]); // chunk hidden, ORG filtered out
    const org = r.graph.legends.types.find((t) => t.type === "ORG")!;
    expect(org.active).toBe(false);
  });
});

describe("renderGraph — communities are groups, not nodes", () => {
  const state: GraphState = {
    nodes: [
      node({ id: "e1", layer: "entity" }),
      node({ id: "e2", layer: "entity" }),
      node({ id: "c", layer: "community", type: "COMMUNITY", name: "Cluster A" }),
    ],
    edges: [
      edge("m1", "e1", "c", { type: "member_of" }),
      edge("m2", "e2", "c", { type: "member_of" }),
    ],
    journal: [],
  };
  it("emits a group with members instead of a community node + member_of edges", () => {
    const r = renderGraph(state, META);
    expect(r.graph.nodes.map((n) => n.id).sort()).toEqual(["e1", "e2"]); // no community node
    expect(r.graph.links).toHaveLength(0); // member_of dropped
    expect(r.graph.groups).toHaveLength(1);
    expect(r.graph.groups[0]).toMatchObject({ name: "Cluster A" });
    expect(r.graph.groups[0]!.memberIds.sort()).toEqual(["e1", "e2"]);
  });
});

describe("renderGraph — temporal axis", () => {
  // n1 recorded from day 1; n2 only recorded from day 3.
  const state: GraphState = {
    nodes: [
      node({ id: "n1", txFrom: "2021-01-01T00:00:00.000Z" }),
      node({ id: "n2", txFrom: "2021-01-03T00:00:00.000Z" }),
    ],
    edges: [edge("e", "n1", "n2", { txFrom: "2021-01-03T00:00:00.000Z" })],
    journal: [],
  };

  it("asOf before a node's txFrom hides it (and its edges)", () => {
    const r = renderGraph(state, META, { asOf: "2021-01-02T00:00:00.000Z", axis: "tx" });
    expect(r.graph.nodes.map((n) => n.id)).toEqual(["n1"]);
    expect(r.graph.links).toHaveLength(0);
  });

  it("asOf after both txFroms shows the whole graph", () => {
    const r = renderGraph(state, META, { asOf: "2021-01-04T00:00:00.000Z", axis: "tx" });
    expect(r.graph.nodes).toHaveLength(2);
    expect(r.graph.links).toHaveLength(1);
  });
});
