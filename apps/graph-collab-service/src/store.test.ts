import { describe, it, expect, beforeEach } from "vitest";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import type { GraphMeta, GraphState, JournalEntry } from "@graphcraft/core";
import { newId, nowIso } from "@graphcraft/core";
import { GraphStore, ConcurrentEditError } from "./store.js";

function sample(): { meta: GraphMeta; base: GraphState } {
  const nodes = [
    { id: "a", graphId: "g1", layer: "entity" as const, type: "PERSON", granularity: 1, name: "A", attributes: {}, provenance: [] },
    { id: "b", graphId: "g1", layer: "entity" as const, type: "PERSON", granularity: 1, name: "B", attributes: {}, provenance: [] },
  ];
  const meta: GraphMeta = {
    id: "g1",
    name: "Sample",
    language: "en",
    version: 0,
    createdAt: nowIso(),
    nodeCount: 2,
    edgeCount: 0,
    layersPresent: ["entity"],
  };
  return { meta, base: { nodes, edges: [], journal: [] } };
}

const entry = (op: JournalEntry["op"], payload: Record<string, unknown>): JournalEntry => ({
  id: newId(),
  graphId: "g1",
  op,
  payload,
  actor: "user:test",
  createdAt: nowIso(),
});

let dir: string;
beforeEach(async () => {
  dir = await fs.mkdtemp(path.join(os.tmpdir(), "gc-store-"));
});

describe("GraphStore", () => {
  it("saves, loads and replays", async () => {
    const store = new GraphStore(dir);
    const { meta, base } = sample();
    await store.saveGraph(meta, base);
    const state = await store.getState("g1");
    expect(state.nodes.map((n) => n.id).sort()).toEqual(["a", "b"]);
  });

  it("appendEntry bumps version, persists, and survives reload", async () => {
    const store = new GraphStore(dir);
    const { meta, base } = sample();
    await store.saveGraph(meta, base);
    const r = await store.appendEntry("g1", entry("update_node_name", { nodeId: "a", name: "Alpha" }), 0);
    expect(r.version).toBe(1);
    expect(r.current.nodes.find((n) => n.id === "a")!.name).toBe("Alpha");

    // fresh store instance → reads from disk
    const store2 = new GraphStore(dir);
    const state = await store2.getState("g1");
    expect(state.nodes.find((n) => n.id === "a")!.name).toBe("Alpha");
    expect((await store2.getMeta("g1")).version).toBe(1);
  });

  it("rejects stale writes with ConcurrentEditError", async () => {
    const store = new GraphStore(dir);
    const { meta, base } = sample();
    await store.saveGraph(meta, base);
    await store.appendEntry("g1", entry("update_node_name", { nodeId: "a", name: "X" }), 0);
    await expect(
      store.appendEntry("g1", entry("update_node_name", { nodeId: "b", name: "Y" }), 0),
    ).rejects.toBeInstanceOf(ConcurrentEditError);
  });

  it("revertLast undoes the last entry", async () => {
    const store = new GraphStore(dir);
    const { meta, base } = sample();
    await store.saveGraph(meta, base);
    await store.appendEntry("g1", entry("delete_node", { nodeId: "b" }), 0);
    expect((await store.getState("g1")).nodes).toHaveLength(1);
    const rev = await store.revertLast("g1", 1);
    expect(rev.removed.op).toBe("delete_node");
    expect((await store.getState("g1")).nodes).toHaveLength(2);
  });

  it("setPinned overlays node.pinned without bumping version", async () => {
    const store = new GraphStore(dir);
    const { meta, base } = sample();
    await store.saveGraph(meta, base);
    await store.setPinned("g1", ["a"], true);
    const state = await store.getState("g1");
    expect(state.nodes.find((n) => n.id === "a")!.pinned).toBe(true);
    expect((await store.getMeta("g1")).version).toBe(0);
  });
});
