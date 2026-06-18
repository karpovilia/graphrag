import { describe, it, expect } from "vitest";
import { reconcile, buildAliasIndex } from "./reconcile.js";
import { applyJournalOp } from "../engine/applier.js";
import { makeEdge, makeEntry, makeNode, makeState } from "../test-helpers.js";

const NOW = "2026-02-01T00:00:00.000Z";

describe("buildAliasIndex", () => {
  it("maps absorbed names to the survivor (chains collapsed)", () => {
    // ivan survives a merge that absorbed "Ваня"; later ivan is absorbed by "I."
    let st = makeState({
      nodes: [
        makeNode({ id: "ivan", name: "Иван Чепиков", type: "PERSON" }),
        makeNode({ id: "vanya", name: "Ваня", type: "PERSON" }),
        makeNode({ id: "ic", name: "I.C.", type: "PERSON" }),
      ],
    });
    st = applyJournalOp(st, makeEntry("merge_nodes", { survivorId: "ivan", absorbedIds: ["vanya"], absorbedNames: ["Ваня"] }));
    st = applyJournalOp(st, makeEntry("merge_nodes", { survivorId: "ic", absorbedIds: ["ivan"], absorbedNames: ["Иван Чепиков"] }));
    const idx = buildAliasIndex(st);
    // "Ваня" should resolve through the chain to the final survivor "ic"
    expect(idx.aliasToSurvivor.get("ваня")).toBe("ic");
  });
});

describe("reconcile — day-2 ingestion respects prior curation", () => {
  // existing curated graph: Ваня was merged into Иван Чепиков
  function base() {
    let st = makeState({
      nodes: [
        makeNode({ id: "ivan", name: "Иван Чепиков", type: "PERSON" }),
        makeNode({ id: "vanya", name: "Ваня", type: "PERSON" }),
        makeNode({ id: "hse", name: "ВШЭ", type: "ORG" }),
      ],
      edges: [makeEdge({ id: "e1", sourceId: "ivan", targetId: "hse", relation: "работает в" })],
    });
    st = applyJournalOp(st, makeEntry("merge_nodes", { survivorId: "ivan", absorbedIds: ["vanya"], absorbedNames: ["Ваня"] }));
    return st;
  }

  it("re-seen alias auto-merges into the prior survivor (not a fresh dup)", () => {
    const existing = base();
    // new doc mentions "Ваня" again + a relation
    const delta = makeState({
      nodes: [makeNode({ id: "d_vanya", name: "Ваня", type: "PERSON" }), makeNode({ id: "d_msk", name: "Москва", type: "PLACE" })],
      edges: [makeEdge({ id: "d_e", sourceId: "d_vanya", targetId: "d_msk", relation: "живёт в" })],
    });
    const r = reconcile(existing, delta, { now: NOW, actor: "agent:ingest" });

    // "Ваня" added then auto-merged into ivan
    expect(r.linked).toContainEqual({ deltaId: "d_vanya", existingId: "ivan", via: "alias" });
    expect(r.journalEntries.some((j) => j.op === "merge_nodes" && (j.payload as any).survivorId === "ivan")).toBe(true);
    // Москва is genuinely new
    expect(r.added).toContain("d_msk");
    // new nodes stamped with the ingestion tx time
    expect(r.addNodes.every((n) => n.txFrom === NOW)).toBe(true);
  });

  it("exact existing entity is reused, not duplicated", () => {
    const existing = base();
    const delta = makeState({ nodes: [makeNode({ id: "d_hse", name: "ВШЭ", type: "ORG" })] });
    const r = reconcile(existing, delta, { now: NOW });
    expect(r.linked).toContainEqual({ deltaId: "d_hse", existingId: "hse", via: "exact" });
    expect(r.added).not.toContain("d_hse");
    expect(r.addNodes.find((n) => n.id === "d_hse")).toBeUndefined();
  });

  it("flags incoming data that contradicts a verified fact (does not overwrite)", () => {
    let existing = base();
    // verify an attribute on Иван
    existing = applyJournalOp(existing, makeEntry("set_attribute", { nodeId: "ivan", key: "роль", value: "lead" }));
    existing = applyJournalOp(existing, makeEntry("set_verified", { nodeId: "ivan", attrKey: "роль", verified: true }));
    const delta = makeState({ nodes: [makeNode({ id: "d_ivan", name: "Иван Чепиков", type: "PERSON", attributes: { роль: "intern" } })] });
    const r = reconcile(existing, delta, { now: NOW });
    expect(r.conflicts).toContainEqual({ nodeId: "ivan", key: "роль", existing: "lead", incoming: "intern", reason: "verified" });
  });

  it("drops edges that duplicate an existing relation", () => {
    const existing = base(); // has ivan→hse "работает в"
    const delta = makeState({
      nodes: [makeNode({ id: "d_ivan", name: "Иван Чепиков", type: "PERSON" }), makeNode({ id: "d_hse", name: "ВШЭ", type: "ORG" })],
      edges: [makeEdge({ id: "d_e", sourceId: "d_ivan", targetId: "d_hse", relation: "работает в" })],
    });
    const r = reconcile(existing, delta, { now: NOW });
    // both endpoints resolve to existing ivan/hse → edge duplicates e1 → dropped
    expect(r.addEdges).toHaveLength(0);
  });
});
