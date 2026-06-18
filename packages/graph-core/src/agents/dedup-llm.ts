import type { Node } from "../domain/graph.js";
import type { Suggestion } from "../domain/journal.js";
import { newId, nowIso } from "../domain/types.js";
import type { GraphState } from "../engine/state.js";
import type { CompletionClient } from "../llm/base.js";
import { extractJson } from "../llm/base.js";
import { entityNodes } from "./util.js";

export interface LlmDedupParams {
  /** restrict to one entity type (default: all types with ≥2 entities). */
  type?: string;
  /** skip types with more than this many entities (prompt too big). */
  maxPerType?: number;
  /** cap how many types to process (busiest first). */
  maxTypes?: number;
}

const SYS = (type: string) =>
  `You deduplicate entities of type ${type} from a knowledge graph. Group names that denote the SAME real-world entity — transliteration variants (Evgeny/Yevgeny), nicknames (Evgeny/Zhenya), abbreviations, with/without patronymic or company suffix. Return JSON {"clusters":[{"canonical":"<best full name>","members":["exact input name", ...]}]}. Only clusters with 2+ members. Use the EXACT input names. Output ONLY the JSON.`;

/** LLM-powered dedup: cluster same-type entities into duplicate groups via the
 *  model, emit MERGE suggestions (same shape as the heuristic dedup agent).
 *  Catches transliteration/nickname dupes the string heuristic misses. */
export async function llmDedup(
  state: GraphState,
  llm: CompletionClient,
  params: LlmDedupParams = {},
): Promise<Suggestion[]> {
  const maxPerType = params.maxPerType ?? 150;
  const maxTypes = params.maxTypes ?? 20;
  const ents: Node[] = entityNodes(state.nodes).filter((n) => !n.pinned);

  const byType = new Map<string, Node[]>();
  for (const n of ents) (byType.get(n.type) ?? byType.set(n.type, []).get(n.type)!).push(n);

  let types = [...byType.entries()].filter(([, ns]) => ns.length >= 2);
  if (params.type) types = types.filter(([t]) => t === params.type);
  types.sort((a, b) => b[1].length - a[1].length);
  types = types.slice(0, maxTypes);

  const out: Suggestion[] = [];
  const graphId = state.nodes[0]?.graphId ?? "";

  for (const [type, nodes] of types) {
    if (nodes.length > maxPerType) continue; // prompt would be too large
    const byName = new Map<string, Node[]>();
    for (const n of nodes) (byName.get(n.name.toLowerCase()) ?? byName.set(n.name.toLowerCase(), []).get(n.name.toLowerCase())!).push(n);
    const names = [...new Set(nodes.map((n) => n.name))];
    type Parsed = { clusters?: { canonical?: string; members?: string[] }[] };
    let parsed: Parsed | null = null;
    try {
      const { text } = await llm.complete(
        [{ role: "system", content: SYS(type) }, { role: "user", content: names.map((n) => `- ${n}`).join("\n") }],
        { temperature: 0.1, maxTokens: 4000, jsonObject: true },
      );
      parsed = extractJson(text) as Parsed | null;
    } catch {
      continue;
    }
    for (const cl of parsed?.clusters ?? []) {
      const members: Node[] = (cl.members ?? []).flatMap((m) => byName.get(String(m).toLowerCase()) ?? []);
      const uniq: Node[] = Array.from(new Map(members.map((n): [string, Node] => [n.id, n])).values());
      if (uniq.length < 2) continue;
      // survivor = name matching canonical, else the longest name
      const canon = String(cl.canonical ?? "").toLowerCase();
      const survivor = uniq.find((n) => n.name.toLowerCase() === canon) ?? [...uniq].sort((a, b) => b.name.length - a.name.length)[0]!;
      const absorbed = uniq.filter((n) => n.id !== survivor.id);
      out.push({
        id: newId(),
        graphId,
        agent: "dedup-llm",
        action: "merge",
        targetNodeIds: [survivor.id, ...absorbed.map((n) => n.id)],
        targetEdgeIds: [],
        payload: {
          survivorId: survivor.id,
          absorbedIds: absorbed.map((n) => n.id),
          reason: `LLM dedup (${type}): same entity as «${survivor.name}»`,
          survivorName: survivor.name,
          absorbedNames: absorbed.map((n) => n.name),
          entityType: type,
        },
        confidence: 0.85,
        rationale: `«${absorbed.map((n) => n.name).join("», «")}» = «${survivor.name}» (${type}, LLM).`,
        evidence: [],
        status: "pending",
        createdAt: nowIso(),
      });
    }
  }
  return out;
}
