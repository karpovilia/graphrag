import { describe, it, expect } from "vitest";
import { liveAt, materializeAt, temporalDiff } from "./temporal.js";
import { makeNode, makeEdge, makeState } from "../test-helpers.js";

describe("liveAt", () => {
  it("tx axis: requires txFrom, half-open end", () => {
    const n = makeNode({ txFrom: "2026-01-01T00:00:00Z", txTo: "2026-02-01T00:00:00Z" });
    expect(liveAt(n, "2025-12-31T00:00:00Z", "tx")).toBe(false);
    expect(liveAt(n, "2026-01-15T00:00:00Z", "tx")).toBe(true);
    expect(liveAt(n, "2026-02-01T00:00:00Z", "tx")).toBe(false); // exclusive end
    expect(liveAt(makeNode({ txFrom: null }), "2026-01-15T00:00:00Z", "tx")).toBe(false);
  });

  it("valid axis: timeless, point, open border", () => {
    const timeless = makeNode({});
    expect(liveAt(timeless, "2026-06-13T00:00:00Z", "valid")).toBe(true);
    const point = makeNode({ validFrom: "2026-03-03T00:00:00Z", validTo: "2026-03-03T00:00:00Z" });
    expect(liveAt(point, "2026-03-03T00:00:00Z", "valid")).toBe(true);
    expect(liveAt(point, "2026-03-04T00:00:00Z", "valid")).toBe(false);
  });
});

describe("temporalDiff", () => {
  it("classifies born / dead / persisted / invalidated", () => {
    const persisted = makeNode({ id: "p", txFrom: "2026-01-01T00:00:00Z" });
    const born = makeNode({ id: "b", txFrom: "2026-02-01T00:00:00Z" });
    const dead = makeNode({ id: "d", txFrom: "2026-01-01T00:00:00Z", txTo: "2026-01-20T00:00:00Z" });
    const liveEdge = makeEdge({
      id: "le",
      sourceId: "p",
      targetId: "b",
      txFrom: "2026-02-01T00:00:00Z",
    });
    const killedEdge = makeEdge({
      id: "ke",
      sourceId: "p",
      targetId: "d",
      txFrom: "2026-01-01T00:00:00Z",
      txTo: "2026-01-20T00:00:00Z",
      invalidation: { at: "2026-01-20T00:00:00Z", reason: "x", auto: false },
    });
    const state = makeState({ nodes: [persisted, born, dead], edges: [liveEdge, killedEdge] });

    const diff = temporalDiff(state, {
      graphId: "g",
      axis: "tx",
      tA: "2026-01-10T00:00:00Z",
      tB: "2026-02-10T00:00:00Z",
    });
    expect(diff.born.map((x) => x.id).sort()).toEqual(["b", "le"]);
    expect(diff.dead.map((x) => x.id)).toEqual(["d"]);
    expect(diff.persisted.map((x) => x.id)).toEqual(["p"]);
    expect(diff.invalidated.map((x) => x.id)).toEqual(["ke"]);
  });

  it("detects community moves between instants", () => {
    const n = makeNode({ id: "n", txFrom: "2026-01-01T00:00:00Z" });
    const c1 = makeNode({ id: "c1", layer: "community", txFrom: "2026-01-01T00:00:00Z" });
    const c2 = makeNode({ id: "c2", layer: "community", txFrom: "2026-01-01T00:00:00Z" });
    // old membership dies at t=20, new membership born at t=20
    const m1 = makeEdge({
      id: "m1", type: "member_of", sourceId: "n", targetId: "c1",
      txFrom: "2026-01-01T00:00:00Z", txTo: "2026-01-20T00:00:00Z",
    });
    const m2 = makeEdge({
      id: "m2", type: "member_of", sourceId: "n", targetId: "c2",
      txFrom: "2026-01-20T00:00:00Z",
    });
    const state = makeState({ nodes: [n, c1, c2], edges: [m1, m2] });
    const diff = temporalDiff(state, {
      graphId: "g", axis: "tx",
      tA: "2026-01-10T00:00:00Z", tB: "2026-01-25T00:00:00Z",
    });
    expect(diff.movedCommunity.map((x) => x.id)).toContain("n");
    const moved = diff.movedCommunity.find((x) => x.id === "n")!;
    expect(moved.fromCommunityId).toBe("c1");
    expect(moved.toCommunityId).toBe("c2");
  });

  it("materializeAt filters to live facts", () => {
    const state = makeState({
      nodes: [
        makeNode({ id: "x", txFrom: "2026-01-01T00:00:00Z" }),
        makeNode({ id: "y", txFrom: "2026-03-01T00:00:00Z" }),
      ],
    });
    const at = materializeAt(state, "2026-02-01T00:00:00Z", "tx");
    expect(at.nodes.map((n) => n.id)).toEqual(["x"]);
  });
});
