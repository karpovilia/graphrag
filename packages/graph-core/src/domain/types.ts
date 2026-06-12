/** Shared primitives. Ids are UUID strings; timestamps are ISO-8601 UTC
 *  strings (keeps graph.json / journal.jsonl trivially serializable and
 *  git-diffable). */

export type Id = string;

export const newId = (): Id => crypto.randomUUID();

export const nowIso = (): string => new Date().toISOString();

/** Epoch millis for a timestamp; null/undefined → null (used by the
 *  bi-temporal comparisons, which treat null as an open border). */
export const ms = (t: string | null | undefined): number | null =>
  t == null ? null : Date.parse(t);

/** Where a piece of graph data came from in the source corpus. */
export interface Provenance {
  documentId: Id;
  spanStart: number;
  spanEnd: number;
  extractedByRunId?: Id | null;
  confidence?: number | null;
}
