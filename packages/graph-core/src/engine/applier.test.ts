import { describe, it, expect } from "vitest";
import { applyJournalOp, replayJournal, affectedSet } from "./applier.js";
import { makeNode, makeEdge, makeState, makeEntry } from "../test-helpers.js";

describe("applier", () => {
  it("merge_nodes redirects edges, drops absorbed, optional rename", () => {
    const a = makeNode({ id: "a", name: "Иван Чепиков" });
    const b = makeNode({ id: "b", name: "Ваня" });
    const c = makeNode({ id: "c", name: "HSE" });
    const e1 = makeEdge({ id: "e1", sourceId: "b", targetId: "c" });
    const state = makeState({ nodes: [a, b, c], edges: [e1] });

    const out = applyJournalOp(
      state,
      makeEntry("merge_nodes", {
        survivorId: "a",
        absorbedIds: ["b"],
        newName: "Иван Чепиков (HSE)",
      }),
    );

    expect(out.nodes.map((n) => n.id).sort()).toEqual(["a", "c"]);
    expect(out.nodes.find((n) => n.id === "a")!.name).toBe("Иван Чепиков (HSE)");
    // edge b→c redirected to a→c
    expect(out.edges).toHaveLength(1);
    expect(out.edges[0]!.sourceId).toBe("a");
    expect(out.edges[0]!.targetId).toBe("c");
    // pure: input untouched
    expect(state.nodes).toHaveLength(3);
  });

  it("merge dedups parallel edges and drops self-loops", () => {
    const a = makeNode({ id: "a" });
    const b = makeNode({ id: "b" });
    const c = makeNode({ id: "c" });
    const state = makeState({
      nodes: [a, b, c],
      edges: [
        makeEdge({ id: "e1", sourceId: "a", targetId: "c", relation: "r" }),
        makeEdge({ id: "e2", sourceId: "b", targetId: "c", relation: "r" }),
        makeEdge({ id: "e3", sourceId: "a", targetId: "b" }), // becomes self-loop
      ],
    });
    const out = applyJournalOp(
      state,
      makeEntry("merge_nodes", { survivorId: "a", absorbedIds: ["b"] }),
    );
    // e2 (a→c r) dedups with e1; e3 self-loop dropped → 1 edge
    expect(out.edges).toHaveLength(1);
    expect(out.edges[0]!.id).toBe("e1");
  });

  it("merge refuses survivor in absorbed list", () => {
    const state = makeState({ nodes: [makeNode({ id: "a" })] });
    expect(() =>
      applyJournalOp(
        state,
        makeEntry("merge_nodes", { survivorId: "a", absorbedIds: ["a"] }),
      ),
    ).toThrow();
  });

  it("split_node creates pieces and reroutes edges by edgeRedirect", () => {
    const o = makeNode({ id: "o", name: "Dept" });
    const x = makeNode({ id: "x" });
    const y = makeNode({ id: "y" });
    const state = makeState({
      nodes: [o, x, y],
      edges: [
        makeEdge({ id: "e1", sourceId: "o", targetId: "x" }),
        makeEdge({ id: "e2", sourceId: "o", targetId: "y" }),
      ],
    });
    const out = applyJournalOp(
      state,
      makeEntry("split_node", {
        originalId: "o",
        newNodes: [
          { id: "o1", layer: "entity", type: "ORG", name: "Dept A" },
          { id: "o2", layer: "entity", type: "ORG", name: "Dept B" },
        ],
        edgeRedirect: { e2: "o2" },
      }),
    );
    expect(out.nodes.map((n) => n.id).sort()).toEqual(["o1", "o2", "x", "y"]);
    const e1 = out.edges.find((e) => e.id === "e1")!;
    const e2 = out.edges.find((e) => e.id === "e2")!;
    expect(e1.sourceId).toBe("o1"); // fallback = first piece
    expect(e2.sourceId).toBe("o2"); // explicit redirect
  });

  it("delete_edge: hard delete vs soft invalidation", () => {
    const state = makeState({
      nodes: [makeNode({ id: "a" }), makeNode({ id: "b" })],
      edges: [makeEdge({ id: "e1", sourceId: "a", targetId: "b" })],
    });
    const hard = applyJournalOp(
      state,
      makeEntry("delete_edge", { edgeId: "e1" }),
    );
    expect(hard.edges).toHaveLength(0);

    const soft = applyJournalOp(
      state,
      makeEntry(
        "delete_edge",
        { edgeId: "e1", reason: "superseded", supersededAt: "2026-01-01T00:00:00Z" },
        "agent:claude",
      ),
    );
    expect(soft.edges).toHaveLength(1);
    expect(soft.edges[0]!.txTo).toBe("2026-01-01T00:00:00Z");
    expect(soft.edges[0]!.invalidation!.reason).toBe("superseded");
    expect(soft.edges[0]!.invalidation!.auto).toBe(true);
  });

  it("edit_edge rejects unknown fields", () => {
    const state = makeState({
      nodes: [makeNode({ id: "a" }), makeNode({ id: "b" })],
      edges: [makeEdge({ id: "e1", sourceId: "a", targetId: "b" })],
    });
    expect(() =>
      applyJournalOp(
        state,
        makeEntry("edit_edge", { edgeId: "e1", updates: { nope: 1 } }),
      ),
    ).toThrow();
    const ok = applyJournalOp(
      state,
      makeEntry("edit_edge", { edgeId: "e1", updates: { relation: "works_at" } }),
    );
    expect(ok.edges[0]!.relation).toBe("works_at");
  });

  it("move_to_community swaps the member_of edge", () => {
    const n = makeNode({ id: "n" });
    const c1 = makeNode({ id: "c1", layer: "community" });
    const c2 = makeNode({ id: "c2", layer: "community" });
    const state = makeState({
      nodes: [n, c1, c2],
      edges: [makeEdge({ id: "m", type: "member_of", sourceId: "n", targetId: "c1" })],
    });
    const out = applyJournalOp(
      state,
      makeEntry("move_to_community", {
        nodeId: "n",
        toCommunityId: "c2",
        fromCommunityId: "c1",
      }),
    );
    const member = out.edges.filter((e) => e.type === "member_of");
    expect(member).toHaveLength(1);
    expect(member[0]!.targetId).toBe("c2");
  });

  it("replayJournal reproduces apply chain", () => {
    const base = makeState({
      nodes: [makeNode({ id: "a", name: "A" }), makeNode({ id: "b", name: "B" })],
    });
    const e1 = makeEntry("update_node_name", { nodeId: "a", name: "A2" });
    const e2 = makeEntry("delete_node", { nodeId: "b" });
    const direct = applyJournalOp(applyJournalOp(base, e1), e2);
    const replayed = replayJournal(base, [e1, e2]);
    expect(replayed.nodes).toEqual(direct.nodes);
    expect(replayed.journal).toHaveLength(2);
  });

  it("affectedSet reports touched nodes/edges/communities", () => {
    const n = makeNode({ id: "n" });
    const c = makeNode({ id: "c", layer: "community" });
    const state = makeState({
      nodes: [n, c],
      edges: [makeEdge({ id: "m", type: "member_of", sourceId: "n", targetId: "c" })],
    });
    const aff = affectedSet(state, makeEntry("retype_node", { nodeId: "n", newType: "ORG" }));
    expect(aff.nodeIds.has("n")).toBe(true);
    expect(aff.communityIds.has("c")).toBe(true);
  });
});
