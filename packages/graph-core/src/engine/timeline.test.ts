import { describe, it, expect } from "vitest";
import { buildTimeline } from "./timeline.js";
import { makeEdge, makeEntry, makeNode, makeState } from "../test-helpers.js";

describe("buildTimeline — activity histogram", () => {
  it("buckets births/deaths per instant on the tx axis", () => {
    const state = makeState({
      nodes: [
        makeNode({ id: "a", txFrom: "2021-01-01T00:00:00.000Z" }),
        makeNode({ id: "b", txFrom: "2021-01-01T00:00:00.000Z" }),
        // born later, and retired even later
        makeNode({ id: "c", txFrom: "2021-03-01T00:00:00.000Z", txTo: "2021-04-01T00:00:00.000Z" }),
      ],
      edges: [makeEdge({ id: "e", sourceId: "a", targetId: "b", txFrom: "2021-01-01T00:00:00.000Z" })],
    });
    const tl = buildTimeline(state, "tx");

    // three distinct instants: the big import day, the c-birth, the c-death
    expect(tl.events.map((e) => e.at)).toEqual([
      "2021-01-01T00:00:00.000Z",
      "2021-03-01T00:00:00.000Z",
      "2021-04-01T00:00:00.000Z",
    ]);
    // day 1: a + b + edge born = 3
    expect(tl.events[0]).toMatchObject({ bornCount: 3, deadCount: 0, eventCount: 3 });
    // c born
    expect(tl.events[1]).toMatchObject({ bornCount: 1, deadCount: 0, eventCount: 1 });
    // c dead
    expect(tl.events[2]).toMatchObject({ bornCount: 0, deadCount: 1, eventCount: 1 });
    expect(tl.min).toBe("2021-01-01T00:00:00.000Z");
    expect(tl.max).toBe("2021-04-01T00:00:00.000Z");
  });

  it("counts timeless nodes (no from-stamp) as genesis", () => {
    const state = makeState({
      nodes: [
        makeNode({ id: "g1", txFrom: null }),
        makeNode({ id: "g2", txFrom: null }),
        makeNode({ id: "n", txFrom: "2022-01-01T00:00:00.000Z" }),
      ],
    });
    const tl = buildTimeline(state, "tx");
    expect(tl.genesisCount).toBe(2);
    expect(tl.genesisNodeIds.sort()).toEqual(["g1", "g2"]);
    expect(tl.events).toHaveLength(1);
  });

  it("folds journal ops into the tx heatmap as dated activity cells", () => {
    const state = makeState({
      // everything imported at one instant (collapses to one stamp bucket)
      nodes: [
        makeNode({ id: "a", txFrom: "2026-01-01T00:00:00.000Z" }),
        makeNode({ id: "b", txFrom: "2026-01-01T00:00:00.000Z" }),
      ],
      // two later curation ops at distinct times → two extra cells
      journal: [
        makeEntry("merge_nodes", { survivorId: "a", absorbedIds: ["b"] }),
        makeEntry("retype_node", { nodeId: "a", newType: "ORG" }),
      ].map((e, i) => ({ ...e, createdAt: `2026-02-0${i + 1}T00:00:00.000Z` })),
    });
    const tx = buildTimeline(state, "tx");
    expect(tx.events).toHaveLength(3); // import + 2 ops
    expect(tx.events[0]).toMatchObject({ bornCount: 2, opCount: 0 });
    expect(tx.events[1]).toMatchObject({ opCount: 1, eventCount: 1 });
    expect(tx.events[2]).toMatchObject({ opCount: 1 });
    // valid axis ignores the journal (createdAt is transaction time)
    expect(buildTimeline(state, "valid").events.every((e) => e.opCount === 0)).toBe(true);
  });

  it("uses valid stamps on the valid axis (independent of tx)", () => {
    const state = makeState({
      nodes: [
        makeNode({ id: "a", txFrom: "2021-01-01T00:00:00.000Z", validFrom: "1990-01-01T00:00:00.000Z" }),
      ],
    });
    expect(buildTimeline(state, "valid").events[0]?.at).toBe("1990-01-01T00:00:00.000Z");
    expect(buildTimeline(state, "tx").events[0]?.at).toBe("2021-01-01T00:00:00.000Z");
  });
});
