import type { JournalEntry } from "../domain/journal.js";
import type {
  CompiledSkill,
  OpStep,
  SkillScope,
  SkillTier,
} from "../domain/skill.js";
import { newId, nowIso, type Id } from "../domain/types.js";
import { extractJson, type CompletionClient } from "../llm/base.js";

/** Id-bearing payload keys → replaced with `<param:KEY>` so the skill is
 *  re-targetable. Free-text keys that vary per instance are dropped so
 *  identical ops with different prose collapse during dedup. */
const ID_KEYS = new Set([
  "nodeId",
  "survivorId",
  "absorbedIds",
  "edgeId",
  "originalId",
  "toCommunityId",
  "fromCommunityId",
]);
const DROP_KEYS = new Set(["reason", "survivorName", "absorbedNames"]);

export function normalisePayload(
  payload: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(payload)) {
    if (DROP_KEYS.has(k)) continue;
    out[k] = ID_KEYS.has(k) ? `<param:${k}>` : v;
  }
  return out;
}

const sortedJson = (v: unknown): string =>
  JSON.stringify(v, (_k, val) =>
    val && typeof val === "object" && !Array.isArray(val)
      ? Object.fromEntries(Object.entries(val).sort(([a], [b]) => a.localeCompare(b)))
      : val,
  );

export interface CompileInput {
  graphId: Id;
  name: string;
  intent?: string;
  entries: JournalEntry[];
  scope: SkillScope;
  tier: SkillTier;
}

/** A human-readable fallback rule from the op sequence + scope. Used for
 *  the structural/embedding tiers and when no LLM is available. */
export function templateRule(seq: OpStep[], scope: SkillScope): string {
  const ops = [...new Set(seq.map((s) => s.op))].join(", ");
  const where =
    scope.kind === "type"
      ? `every entity of type «${scope.type}»`
      : scope.kind === "layer"
        ? `every node in the «${scope.layer}» layer`
        : scope.kind === "graph"
          ? "every node in the graph"
          : "the selected nodes";
  return `Apply [${ops}] to ${where}.`;
}

const RULE_SYSTEM =
  "You help a knowledge-graph curator generalise a series of edits into a " +
  "reusable rule. Given a sequence of journal operations, return EXACTLY 3 " +
  "DISTINCT rule candidates that select targets by DIFFERENT criteria " +
  "(e.g. by name-pattern, by graph topology, by type/layer). Each rule is " +
  "1-2 sentences, if-then style, no UUIDs. The three MUST differ in the " +
  'KIND of criterion. Respond strictly as JSON: {"candidates": ["...", "...", "..."]}.';

async function synthesizeRules(
  tier: SkillTier,
  seq: OpStep[],
  scope: SkillScope,
  samples: { op: string; targetName?: string; keys: string }[],
  intent: string,
  llm: CompletionClient | null,
): Promise<string[]> {
  if (tier !== "llm" || !llm) return [templateRule(seq, scope)];
  const lines = samples
    .slice(0, 20)
    .map((s) => `- ${s.op}: target=«${s.targetName ?? "node"}»; ${s.keys}`);
  const user =
    (intent ? `User intent: ${intent}\n\n` : "") +
    "Observations:\n" +
    lines.join("\n") +
    "\n\nProduce 3 distinct rule candidates as a JSON object.";
  try {
    const { text } = await llm.complete(
      [
        { role: "system", content: RULE_SYSTEM },
        { role: "user", content: user },
      ],
      { temperature: 0.3, maxTokens: 400, jsonObject: true },
    );
    const parsed = extractJson(text) as { candidates?: unknown } | null;
    const cands = parsed?.candidates;
    if (Array.isArray(cands)) {
      const out = cands.filter((c): c is string => typeof c === "string");
      if (out.length) return out;
    }
  } catch {
    /* fall back to template */
  }
  return [templateRule(seq, scope)];
}

/** Pull the chosen journal entries, normalise + dedup their payloads, and
 *  synthesise a reusable skill. Pure aside from the optional LLM call. */
export async function compileSkill(
  input: CompileInput,
  ctx: { llm?: CompletionClient | null; nameById?: Map<Id, string> } = {},
): Promise<CompiledSkill> {
  const raw: OpStep[] = input.entries.map((e) => ({
    op: e.op,
    payload: normalisePayload(e.payload),
  }));

  // Deduplicate identical (op, normalised-payload) signatures — order kept.
  const opSequence: OpStep[] = [];
  const seen = new Set<string>();
  for (const step of raw) {
    const sig = sortedJson(step);
    if (seen.has(sig)) continue;
    seen.add(sig);
    opSequence.push(step);
  }

  const opSummary: Record<string, number> = {};
  for (const s of opSequence) opSummary[s.op] = (opSummary[s.op] ?? 0) + 1;

  const samples = input.entries.map((e) => {
    const nid = (e.payload.nodeId ?? e.payload.survivorId) as string | undefined;
    const targetName = nid ? (ctx.nameById?.get(nid) ?? nid.slice(0, 8)) : undefined;
    const keys = Object.entries(e.payload)
      .filter(([k]) => k !== "nodeId" && k !== "survivorId")
      .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
      .join(", ");
    return { op: e.op, targetName, keys };
  });

  const ruleCandidates = await synthesizeRules(
    input.tier,
    opSequence,
    input.scope,
    samples,
    input.intent ?? "",
    ctx.llm ?? null,
  );

  return {
    id: newId(),
    name: input.name,
    intent: input.intent ?? "",
    graphId: input.graphId,
    sourceEntryIds: input.entries.map((e) => e.id),
    opSequence,
    opSummary,
    ruleCandidates,
    selectedRuleIndex: ruleCandidates.length ? 0 : null,
    ruleOverride: null,
    tier: input.tier,
    scope: input.scope,
    createdAt: nowIso(),
  };
}
