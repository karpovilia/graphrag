import { describe, it, expect, beforeEach } from "vitest";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import type { GraphMeta, GraphState } from "@graphcraft/core";
import { newId, nowIso } from "@graphcraft/core";
import type { ServerMessage } from "@graphcraft/shared";
import { GraphStore } from "./store.js";
import { Room } from "./room.js";

async function freshRoom(): Promise<{ room: Room; msgs: ServerMessage[]; store: GraphStore }> {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "gc-room-"));
  const store = new GraphStore(dir);
  const meta: GraphMeta = {
    id: "g1", name: "S", language: "en", version: 0,
    createdAt: nowIso(), nodeCount: 2, edgeCount: 0, layersPresent: ["entity"],
  };
  const base: GraphState = {
    nodes: [
      { id: "a", graphId: "g1", layer: "entity", type: "PERSON", granularity: 1, name: "A", attributes: {}, provenance: [] },
      { id: "b", graphId: "g1", layer: "entity", type: "PERSON", granularity: 1, name: "B", attributes: {}, provenance: [] },
    ],
    edges: [],
    journal: [],
  };
  await store.saveGraph(meta, base);
  const msgs: ServerMessage[] = [];
  const room = new Room("g1", store, (m) => msgs.push(m));
  await room.init();
  return { room, msgs, store };
}

let ctx: Awaited<ReturnType<typeof freshRoom>>;
beforeEach(async () => {
  ctx = await freshRoom();
});

describe("Room", () => {
  it("applyOp serializes, broadcasts op_applied with a delta", async () => {
    const { room, msgs } = ctx;
    const r = await room.applyOp("user:alice", "retype_node", { nodeId: "a", newType: "ORG" });
    expect(r.version).toBe(1);
    expect(r.delta.counts.nodes_changed).toBe(1);
    const applied = msgs.find((m) => m.type === "op_applied");
    expect(applied).toBeTruthy();
  });

  it("concurrent applyOp calls serialize to consecutive versions", async () => {
    const { room } = ctx;
    const [r1, r2] = await Promise.all([
      room.applyOp("user:alice", "update_node_name", { nodeId: "a", name: "A2" }),
      room.applyOp("user:bob", "update_node_name", { nodeId: "b", name: "B2" }),
    ]);
    expect([r1.version, r2.version].sort()).toEqual([1, 2]);
    expect(room.currentVersion).toBe(2);
  });

  it("decision loop: requestDecision resolves when a human resolves it", async () => {
    const { room, msgs } = ctx;
    const decisionId = newId();
    const pending = room.requestDecision("agent:claude", {
      decisionId,
      kind: "merge",
      proposal: "Merge B into A?",
      op: "merge_nodes",
      payload: { survivorId: "a", absorbedIds: ["b"] },
      nodeIds: ["a", "b"],
      options: ["accept", "reject", "edit", "pin"],
    });
    expect(msgs.some((m) => m.type === "decision_request")).toBe(true);

    room.resolveDecision("user:alice", decisionId, "accept");
    const result = await pending;
    expect(result.choice).toBe("accept");
    expect(result.by).toBe("user:alice");
    expect(msgs.some((m) => m.type === "decision_resolved")).toBe(true);
  });

  it("decision loop: times out when nobody answers", async () => {
    const { room } = ctx;
    const result = await room.requestDecision(
      "agent:claude",
      {
        decisionId: newId(),
        kind: "merge",
        proposal: "x",
        nodeIds: [],
        options: ["accept", "reject"],
      },
      20,
    );
    expect(result.choice).toBe("timeout");
  });

  it("focus + suggestion + presence broadcast", async () => {
    const { room, msgs } = ctx;
    room.join({ actor: "user:alice", name: "Alice", color: "#f00", kind: "human" });
    room.focus("agent:claude", ["a"], "look here");
    room.addSuggestion({
      id: newId(), graphId: "g1", agent: "dedup", action: "merge",
      targetNodeIds: ["a", "b"], targetEdgeIds: [], payload: {},
      confidence: 0.9, rationale: "dup", evidence: [], status: "pending", createdAt: nowIso(),
    });
    expect(msgs.some((m) => m.type === "presence")).toBe(true);
    expect(msgs.some((m) => m.type === "focus")).toBe(true);
    expect(msgs.some((m) => m.type === "suggestion_added")).toBe(true);
    expect(room.listSuggestions()).toHaveLength(1);
  });

  it("pin marks the node pinned in state", async () => {
    const { room, store } = ctx;
    await room.pin(["a"], true);
    const state = await store.getState("g1");
    expect(state.nodes.find((n) => n.id === "a")!.pinned).toBe(true);
  });
});
