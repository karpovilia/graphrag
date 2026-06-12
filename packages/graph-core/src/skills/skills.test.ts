import { describe, it, expect } from "vitest";
import { compileSkill, normalisePayload } from "./compiler.js";
import {
  planSkillRun,
  dryRunSkill,
  resolveScopeNodes,
  isDestructiveRun,
} from "./runner.js";
import type { CompiledSkill } from "../domain/skill.js";
import { makeNode, makeState, makeEntry } from "../test-helpers.js";

describe("skill compiler", () => {
  it("normalises id keys to params and drops reasons", () => {
    const out = normalisePayload({ nodeId: "x", newType: "VERB", reason: "free text" });
    expect(out).toEqual({ nodeId: "<param:nodeId>", newType: "VERB" });
  });

  it("compiles + dedups identical ops, structural tier templates a rule", async () => {
    const entries = [
      makeEntry("delete_node", { nodeId: "a", reason: "verb 1" }),
      makeEntry("delete_node", { nodeId: "b", reason: "verb 2" }),
      makeEntry("delete_node", { nodeId: "c", reason: "verb 3" }),
    ];
    const skill = await compileSkill({
      graphId: "g",
      name: "delete-verbs",
      intent: "delete entities whose name is a verb",
      entries,
      scope: { kind: "type", type: "VERB" },
      tier: "structural",
    });
    expect(skill.opSequence).toHaveLength(1); // 3 deletes collapse to 1 op
    expect(skill.opSummary.delete_node).toBe(1);
    expect(skill.ruleCandidates).toHaveLength(1);
    expect(skill.ruleCandidates[0]).toContain("VERB");
  });

  it("llm tier asks the client for 3 candidates", async () => {
    const fakeLlm = {
      provider: "fake",
      async complete() {
        return { text: JSON.stringify({ candidates: ["r1", "r2", "r3"] }) };
      },
    };
    const skill = await compileSkill(
      {
        graphId: "g",
        name: "s",
        entries: [makeEntry("retype_node", { nodeId: "a", newType: "ORG" })],
        scope: { kind: "graph" },
        tier: "llm",
      },
      { llm: fakeLlm },
    );
    expect(skill.ruleCandidates).toEqual(["r1", "r2", "r3"]);
    expect(skill.selectedRuleIndex).toBe(0);
  });
});

describe("skill runner", () => {
  const skill: CompiledSkill = {
    id: "s",
    name: "retype-verbs",
    intent: "",
    graphId: "g",
    sourceEntryIds: [],
    opSequence: [{ op: "retype_node", payload: { nodeId: "<param:nodeId>", newType: "VERB" } }],
    opSummary: { retype_node: 1 },
    ruleCandidates: [],
    tier: "structural",
    scope: { kind: "type", type: "PERSON" },
    createdAt: "2026-06-13T00:00:00Z",
  };

  it("resolveScopeNodes filters by type", () => {
    const nodes = [
      makeNode({ id: "a", type: "PERSON" }),
      makeNode({ id: "b", type: "ORG" }),
    ];
    expect(resolveScopeNodes({ kind: "type", type: "PERSON" }, nodes).map((n) => n.id)).toEqual(["a"]);
  });

  it("planSkillRun substitutes the param and skips pinned nodes", () => {
    const state = makeState({
      nodes: [
        makeNode({ id: "a", type: "PERSON" }),
        makeNode({ id: "b", type: "PERSON", pinned: true }),
      ],
    });
    const plan = planSkillRun(skill, skill.scope, state, "agent:claude");
    expect(plan.targetNodeIds).toEqual(["a"]); // b pinned → excluded
    expect(plan.entries[0]!.payload.nodeId).toBe("a");
  });

  it("dryRunSkill returns a preview delta without journalling", () => {
    const state = makeState({
      nodes: [makeNode({ id: "a", type: "PERSON" }), makeNode({ id: "c", type: "PERSON" })],
    });
    const { delta, opCount } = dryRunSkill(skill, skill.scope, state);
    expect(opCount).toBe(2);
    expect(delta.counts.nodes_changed).toBe(2);
    expect(state.journal).toHaveLength(0); // untouched
  });

  it("destructive guard trips for many deletes, not for dry-run", () => {
    const del: CompiledSkill = { ...skill, opSequence: [{ op: "delete_node", payload: { nodeId: "<param:nodeId>" } }] };
    expect(isDestructiveRun(del, 50, false)).toBe(true);
    expect(isDestructiveRun(del, 50, true)).toBe(false);
    expect(isDestructiveRun(del, 5, false)).toBe(false);
  });
});
