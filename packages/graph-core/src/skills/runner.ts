import type { Node } from "../domain/graph.js";
import type { JournalEntry, JournalOp } from "../domain/journal.js";
import type { CompiledSkill, SkillScope } from "../domain/skill.js";
import type { CTDGDelta } from "../domain/delta.js";
import { newId, nowIso, type Id } from "../domain/types.js";
import { replayJournal } from "../engine/applier.js";
import type { GraphState } from "../engine/state.js";
import { computeDelta } from "../engine/ctdg.js";

/** Ops that are safely re-targetable per node (others need manual params). */
export const PER_NODE_OPS = new Set<JournalOp>([
  "delete_node",
  "retype_node",
  "update_node_name",
  "set_summary",
]);

/** Above this target count + at least one delete op, a real run refuses
 *  unless explicitly confirmed — stops "run on graph" from wiping a graph. */
export const DESTRUCTIVE_CAP = 10;

export function resolveScopeNodes(scope: SkillScope, nodes: Node[]): Node[] {
  switch (scope.kind) {
    case "selection": {
      const ids = new Set((scope.nodeIds ?? []).map(String));
      return nodes.filter((n) => ids.has(n.id));
    }
    case "layer":
      return scope.layer ? nodes.filter((n) => n.layer === scope.layer) : [];
    case "type":
      return scope.type
        ? nodes.filter(
            (n) => (n.type ?? "").toLowerCase() === scope.type!.toLowerCase(),
          )
        : [];
    case "graph":
      return [...nodes];
  }
}

/** True if a non-dry run would trip the destructive guard. */
export function isDestructiveRun(
  skill: CompiledSkill,
  targetCount: number,
  dryRun: boolean,
): boolean {
  const hasDelete = skill.opSequence.some(
    (s) => s.op === "delete_node" || s.op === "delete_edge",
  );
  return !dryRun && hasDelete && targetCount > DESTRUCTIVE_CAP;
}

export interface SkillPlan {
  entries: JournalEntry[];
  targetNodeIds: Id[];
  /** Pinned targets and non-per-node ops that were skipped, with reasons. */
  skipped: string[];
}

/** Build the journal entries a skill run would append. Pure — does NOT
 *  mutate state. Pinned nodes are excluded (the paper's pin contract). */
export function planSkillRun(
  skill: CompiledSkill,
  scope: SkillScope,
  state: GraphState,
  actor: string,
): SkillPlan {
  const targets = resolveScopeNodes(scope, state.nodes).filter((n) => {
    if (n.pinned) return false;
    return true;
  });
  const entries: JournalEntry[] = [];
  const skipped: string[] = [];
  const targetNodeIds: Id[] = [];

  for (const node of targets) {
    let touched = false;
    for (const step of skill.opSequence) {
      if (!PER_NODE_OPS.has(step.op)) {
        skipped.push(`op '${step.op}' is not per-node re-applicable`);
        continue;
      }
      const payload: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(step.payload)) {
        payload[k] =
          typeof v === "string" && v.startsWith("<param:") ? node.id : v;
      }
      entries.push({
        id: newId(),
        graphId: skill.graphId,
        op: step.op,
        payload,
        actor,
        createdAt: nowIso(),
      });
      touched = true;
    }
    if (touched) targetNodeIds.push(node.id);
  }
  return { entries, targetNodeIds, skipped: [...new Set(skipped)] };
}

/** Apply the plan to a CLONE of state and return a preview delta. Used by
 *  the dry-run that paints the impact set in the delta grammar without
 *  journalling anything. */
export function dryRunSkill(
  skill: CompiledSkill,
  scope: SkillScope,
  state: GraphState,
): { delta: CTDGDelta; targetNodeIds: Id[]; opCount: number } {
  const plan = planSkillRun(skill, scope, state, "preview:dry-run");
  const after = replayJournal(state, plan.entries);
  const delta = computeDelta(state, after, null, {
    explanation:
      `Dry-run of «${skill.name}»: ${plan.entries.length} op(s) over ` +
      `${plan.targetNodeIds.length} target(s).`,
  });
  return {
    delta,
    targetNodeIds: plan.targetNodeIds,
    opCount: plan.entries.length,
  };
}
