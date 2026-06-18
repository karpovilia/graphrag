import type { CompletionClient } from "../llm/base.js";
import { extractJson } from "../llm/base.js";

/** What an extractor pulls out of a single chunk. Mirrors graphrag's
 *  ChunkExtraction (entities + relations). */
export interface ExtractedEntity {
  name: string;
  type: string;
  description?: string;
  /** Optional emergent stratum the model proposes for this entity (beyond the
   *  canonical entity layer) — e.g. "person", "metric", "decision". The
   *  pipeline registers distinct proposed layers per graph. */
  layer?: string;
}
export interface ExtractedRelation {
  source: string;
  target: string;
  predicate?: string;
  description?: string;
  weight?: number;
}
export interface ChunkExtraction {
  entities: ExtractedEntity[];
  relations: ExtractedRelation[];
}

export interface Extractor {
  /** Stable name for meta/source provenance. */
  readonly name: string;
  extract(chunkText: string): Promise<ChunkExtraction>;
}

// ── keyless heuristic extractor (offline default) ──────────────────────────
// Ports the *spirit* of graphrag's NerExtractionBuilder: deterministic,
// no LLM. natasha (its Russian NER) is Python-only, so we use a language-
// agnostic surface heuristic — maximal runs of capitalised tokens — and let
// the pipeline build co-occurrence relations. Lower recall than natasha, but
// keyless and runs in CI; the LLM extractor is the high-quality path.

// alphanumeric tokens; internal . or - allowed (covid-19, U.S.A) but not trailing
const WORD = /[\p{L}\p{N}]+(?:[.\-][\p{L}\p{N}]+)*/gu;
// A token is "name-like" if it starts with an uppercase/title letter.
const isCap = (tok: string) => /^\p{Lu}/u.test(tok);
// Sentence-initial / chat noise words that are capitalised only by position.
// (lower-cased; matched case-insensitively)
const STOP = new Set([
  "the", "a", "an", "this", "that", "these", "those", "it", "he", "she", "they", "we", "you", "i",
  "это", "этот", "эта", "эти", "тот", "она", "он", "они", "мы", "вы", "я", "в", "на", "по", "и", "а", "но",
  "привет", "спасибо", "пожалуйста", "да", "нет", "ок", "окей", "можно", "нужно", "надо", "давай",
  "давайте", "кстати", "здравствуйте", "итак", "ладно", "хорошо", "понятно", "отлично", "супер",
  "коллеги", "всем", "доброе", "добрый", "день", "утро", "вечер", "если", "что", "как", "когда",
  "почему", "там", "тут", "вот", "ещё", "еще", "уже", "просто", "также", "тогда", "сейчас", "потом",
]);
// Russian verb / imperative / participle endings → not an entity.
const VERBISH = /(ите|йте|ьте|уйте|ться|тесь|нибудь|ешь|ёшь|ишь|вший|вшая|вшие|ался|алась|ались)$/i;
const looksLikeVerb = (tok: string) => VERBISH.test(tok);

export function heuristicExtract(chunkText: string): ChunkExtraction {
  const names = new Set<string>();
  let run: string[] = [];
  const flush = () => {
    if (run.length) {
      const name = run.join(" ").trim();
      // multi-token runs are likely proper-name phrases → keep.
      // single tokens must be ≥3 chars, not a stopword, and not verb-shaped.
      const keep = run.length > 1
        ? true
        : name.length >= 3 && !STOP.has(name.toLowerCase()) && !looksLikeVerb(name);
      if (keep) names.add(name);
      run = [];
    }
  };
  // Walk tokens by position so we can break a name run at any punctuation or
  // newline between tokens (the gap text) — capitalised words across a
  // sentence boundary must NOT merge into one entity.
  let prevEnd = -1;
  for (const m of chunkText.matchAll(WORD)) {
    const tok = m[0];
    const start = m.index ?? 0;
    if (prevEnd >= 0) {
      const gap = chunkText.slice(prevEnd, start);
      if (/[^ \t]/.test(gap)) flush(); // punctuation/newline → boundary
    }
    if (isCap(tok) && !STOP.has(tok.toLowerCase())) run.push(tok);
    else flush();
    prevEnd = start + tok.length;
  }
  flush();

  return {
    entities: [...names].map((name) => ({ name, type: "ENTITY" })),
    relations: [], // pipeline derives co-occurrence relations
  };
}

export const heuristicExtractor: Extractor = {
  name: "heuristic",
  extract: (chunkText) => Promise.resolve(heuristicExtract(chunkText)),
};

// ── LLM extractor (LightRAG / Microsoft-style single-pass) ─────────────────
const ALLOWED_TYPES = ["PERSON", "ORG", "PLACE", "EVENT", "CONCEPT", "OBJECT", "MISC"];

const SYSTEM =
  "You extract a knowledge graph from text. For each salient entity give a " +
  "name, a type from this set (" + ALLOWED_TYPES.join(", ") + "), a one-" +
  "sentence description, and a `layer`: a SHORT lowercase noun naming the " +
  "stratum this entity belongs to in THIS corpus (e.g. person, organization, " +
  "metric, decision, artifact, event). Reuse the same layer label across " +
  "entities of the same kind so strata emerge consistently. Also list relations " +
  "between the named entities with a short predicate. Respond STRICTLY as JSON: " +
  '{"entities":[{"name":"...","type":"...","layer":"...","description":"..."}],' +
  '"relations":[{"source":"...","target":"...","predicate":"...","description":"..."}]}. ' +
  "Use the text's own language for names and descriptions; keep `type`/`layer` ascii.";

function coerce(parsed: unknown): ChunkExtraction {
  const obj = (parsed ?? {}) as Record<string, unknown>;
  const ents = Array.isArray(obj.entities) ? obj.entities : [];
  const rels = Array.isArray(obj.relations) ? obj.relations : [];
  const entities: ExtractedEntity[] = [];
  for (const e of ents) {
    const r = e as Record<string, unknown>;
    const name = typeof r.name === "string" ? r.name.trim() : "";
    if (!name) continue;
    const type = typeof r.type === "string" && ALLOWED_TYPES.includes(r.type.toUpperCase())
      ? r.type.toUpperCase()
      : "MISC";
    const layer = typeof r.layer === "string" && r.layer.trim()
      ? r.layer.trim().toLowerCase().replace(/\s+/g, "_")
      : undefined;
    entities.push({ name, type, layer, description: typeof r.description === "string" ? r.description : undefined });
  }
  const known = new Set(entities.map((e) => e.name.toLowerCase()));
  const relations: ExtractedRelation[] = [];
  for (const rel of rels) {
    const r = rel as Record<string, unknown>;
    const source = typeof r.source === "string" ? r.source.trim() : "";
    const target = typeof r.target === "string" ? r.target.trim() : "";
    if (!source || !target || source === target) continue;
    if (!known.has(source.toLowerCase()) || !known.has(target.toLowerCase())) continue;
    relations.push({
      source,
      target,
      predicate: typeof r.predicate === "string" ? r.predicate : undefined,
      description: typeof r.description === "string" ? r.description : undefined,
      weight: typeof r.weight === "number" ? r.weight : undefined,
    });
  }
  return { entities, relations };
}

/** Build an LLM-backed extractor. Resilient: a failed/garbled call yields an
 *  empty extraction for that chunk rather than aborting the whole build. */
export function llmExtractor(
  llm: CompletionClient,
  opts: { model?: string } = {},
): Extractor {
  return {
    name: `llm:${llm.provider}`,
    async extract(chunkText) {
      try {
        const { text } = await llm.complete(
          [
            { role: "system", content: SYSTEM },
            { role: "user", content: chunkText },
          ],
          { temperature: 0, maxTokens: 1500, jsonObject: true, model: opts.model },
        );
        return coerce(extractJson(text));
      } catch {
        return { entities: [], relations: [] };
      }
    },
  };
}
