import { describe, it, expect } from "vitest";
import { applyJournalOp } from "./applier.js";
import { computeDelta } from "./ctdg.js";
import { makeNode, makeEdge, makeState, makeEntry } from "../test-helpers.js";

describe("computeDelta", () => {
  it("emits per-element events + counts for a rename", () => {
    const before = makeState({ nodes: [makeNode({ id: "a", name: "A" })] });
    const entry = makeEntry("update_node_name", { nodeId: "a", name: "A2" });
    const after = applyJournalOp(before, entry);
    const delta = computeDelta(before, after, entry, { explanation: "renamed" });
    expect(delta.op).toBe("update_node_name");
    expect(delta.counts.nodes_changed).toBe(1);
    expect(delta.events.some((e) => e.kind === "node_renamed")).toBe(true);
    expect(delta.affectedNodeIds).toContain("a");
  });

  it("counts removals across nodes and incident edges", () => {
    const before = makeState({
      nodes: [makeNode({ id: "a" }), makeNode({ id: "b" })],
      edges: [makeEdge({ id: "e", sourceId: "a", targetId: "b" })],
    });
    const entry = makeEntry("delete_node", { nodeId: "a" });
    const after = applyJournalOp(before, entry);
    const delta = computeDelta(before, after, entry);
    expect(delta.counts.nodes_removed).toBe(1);
    expect(delta.counts.edges_removed).toBe(1);
  });
});
