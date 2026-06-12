import type { Id } from "./types.js";
import type { JournalOp } from "./journal.js";
import type { Layer } from "./graph.js";

/** The three price points from the paper:
 *  - structural: heuristics, no LLM calls
 *  - embedding : embedding-ranked candidates (+ one verification pass)
 *  - llm       : full three-pass reasoning (form-rule → shortlist → verify) */
export type SkillTier = "structural" | "embedding" | "llm";

export interface OpStep {
  op: JournalOp;
  /** Normalised payload: id-bearing keys replaced with `<param:KEY>`. */
  payload: Record<string, unknown>;
}

/** Where a compiled skill runs. */
export interface SkillScope {
  kind: "selection" | "layer" | "type" | "graph";
  nodeIds?: Id[];
  layer?: Layer | null;
  type?: string | null;
  dryRun?: boolean;
  /** Collapse duplicate ops in the sequence (default true). */
  deduplicateOps?: boolean;
}

/** A user-named recipe extracted from N journal entries. */
export interface CompiledSkill {
  id: Id;
  name: string;
  intent: string;
  graphId: Id;
  sourceEntryIds: Id[];
  opSequence: OpStep[];
  opSummary: Record<string, number>;
  /** LLM-generalised one-liners (or a single templated rule for the
   *  structural tier). The user picks/edits one as the behaviour spec. */
  ruleCandidates: string[];
  selectedRuleIndex?: number | null;
  ruleOverride?: string | null;
  tier: SkillTier;
  scope: SkillScope;
  createdAt: string;
}
