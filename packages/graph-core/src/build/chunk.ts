/** Split raw document text into character-window chunks (ports graphrag's
 *  _llm_extract.chunk_document). Byte/char boundaries, no token awareness —
 *  deterministic and dependency-free. overlap ≥ size is clamped to 0. */
export interface Chunk {
  start: number;
  end: number;
  text: string;
}

export function chunkDocument(
  text: string,
  opts: { size?: number; overlap?: number } = {},
): Chunk[] {
  const size = Math.max(1, opts.size ?? 1200);
  let overlap = opts.overlap ?? 0;
  if (overlap >= size || overlap < 0) overlap = 0;
  const step = size - overlap;

  const chunks: Chunk[] = [];
  const n = text.length;
  if (n === 0) return chunks;
  for (let pos = 0; pos < n; pos += step) {
    const end = Math.min(pos + size, n);
    const slice = text.slice(pos, end);
    if (slice.trim()) chunks.push({ start: pos, end, text: slice });
    if (end >= n) break;
  }
  return chunks;
}
