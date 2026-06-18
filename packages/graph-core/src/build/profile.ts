import type { ParsedDocument } from "../domain/project.js";

/** A read-only profile of a parsed corpus — the "Изучаю данные" step. Cheap:
 *  computed from the parsed documents plus a sample entity-type count handed in
 *  by the caller (so this module never has to run a build itself). Feeds the
 *  scenario ranking and the AI-led setup flow. */
export interface CorpusProfile {
  format: "plain" | "chat";
  docCount: number;
  sampledDocs: number;
  charCount: number;
  estChunks: number;
  /** language mix (share 0..1), Cyrillic vs Latin heuristic. */
  languages: { lang: "ru" | "en"; share: number }[];
  /** event-time span across dated documents (chat). */
  timeSpan: { from: string | null; to: string | null; dated: number };
  /** chat authors by message count (top 8). */
  authors: { name: string; count: number }[];
  /** entity kinds detected on the sample (from a sample build, injected). */
  entityTypes: Record<string, number>;
  /** salient terms across the sample (top 12). */
  topTerms: { term: string; count: number }[];
  /** extractor that produced entityTypes (null = keyless heuristic). */
  provider: string | null;
}

const STOP = new Set([
  "это","что","как","так","для","или","если","того","чтобы","когда","который","которые","также",
  "только","может","быть","есть","было","были","будет","надо","нужно","тебе","меня","себя","нами",
  "всех","всё","все","там","тут","этот","эта","эти","того","при","над","под","про","без","más",
  "the","and","for","that","this","with","from","you","are","was","were","have","has","not","but",
  "can","will","your","our","their","its","into","out","about","they","them","then","than","over",
]);

const isCyr = (c: string) => c >= "Ѐ" && c <= "ӿ";
const isLat = (c: string) => (c >= "a" && c <= "z") || (c >= "A" && c <= "Z");

/** Build a corpus profile from parsed documents. `entityTypes`/`provider` come
 *  from a sample build run by the caller (kept out of here to stay cheap). */
export function analyzeCorpus(
  docs: ParsedDocument[],
  opts: { format: "plain" | "chat"; entityTypes?: Record<string, number>; provider?: string | null; chunkSize?: number; sample?: number },
): CorpusProfile {
  const sampleN = opts.sample ?? 60;
  const sample = docs.slice(0, sampleN);
  const chunkSize = opts.chunkSize ?? 1200;

  let charCount = 0;
  let cyr = 0;
  let lat = 0;
  const terms = new Map<string, number>();
  const authors = new Map<string, number>();
  let minT: string | null = null;
  let maxT: string | null = null;
  let dated = 0;

  for (const d of docs) {
    charCount += d.text.length;
    if (d.validFrom) {
      dated++;
      if (!minT || d.validFrom < minT) minT = d.validFrom;
      if (!maxT || d.validFrom > maxT) maxT = d.validFrom;
    }
    if (d.author) authors.set(d.author, (authors.get(d.author) ?? 0) + 1);
  }

  for (const d of sample) {
    for (const ch of d.text) {
      if (isCyr(ch)) cyr++;
      else if (isLat(ch)) lat++;
    }
    for (const raw of d.text.toLowerCase().split(/[^\p{L}\p{N}]+/u)) {
      if (raw.length < 4 || STOP.has(raw) || /^\d+$/.test(raw)) continue;
      terms.set(raw, (terms.get(raw) ?? 0) + 1);
    }
  }

  const letters = cyr + lat || 1;
  const languages = [
    { lang: "ru" as const, share: cyr / letters },
    { lang: "en" as const, share: lat / letters },
  ].filter((l) => l.share > 0.02).sort((a, b) => b.share - a.share);

  const topTerms = [...terms.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12)
    .map(([term, count]) => ({ term, count }));

  const topAuthors = [...authors.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([name, count]) => ({ name, count }));

  return {
    format: opts.format,
    docCount: docs.length,
    sampledDocs: sample.length,
    charCount,
    estChunks: Math.max(1, Math.round(charCount / chunkSize)),
    languages: languages.length ? languages : [{ lang: "ru", share: 1 }],
    timeSpan: { from: minT, to: maxT, dated },
    authors: topAuthors,
    entityTypes: opts.entityTypes ?? {},
    topTerms,
    provider: opts.provider ?? null,
  };
}
