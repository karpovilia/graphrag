import type { Node } from "../domain/graph.js";
import type { Id } from "../domain/types.js";
import type { GraphState } from "../engine/state.js";

export const entityNodes = (nodes: Node[]): Node[] =>
  nodes.filter((n) => n.layer === "entity");

const tokens = (s: string): string[] =>
  (s || "")
    .toLowerCase()
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean);

function jaccard(a: string, b: string): number {
  const A = new Set(tokens(a));
  const B = new Set(tokens(b));
  if (!A.size || !B.size) return 0;
  let inter = 0;
  for (const x of A) if (B.has(x)) inter++;
  return inter / (A.size + B.size - inter);
}

function bigrams(s: string): string[] {
  const t = (s || "").toLowerCase().replace(/\s+/g, " ").trim();
  const out: string[] = [];
  for (let i = 0; i < t.length - 1; i++) out.push(t.slice(i, i + 2));
  return out;
}

function bigramDice(a: string, b: string): number {
  const A = bigrams(a);
  const B = bigrams(b);
  if (!A.length || !B.length) return 0;
  const counts = new Map<string, number>();
  for (const g of A) counts.set(g, (counts.get(g) ?? 0) + 1);
  let inter = 0;
  for (const g of B) {
    const c = counts.get(g) ?? 0;
    if (c > 0) {
      inter++;
      counts.set(g, c - 1);
    }
  }
  return (2 * inter) / (A.length + B.length);
}

/** Name similarity: max of word-Jaccard and bigram-Dice (so «Ваня» and
 *  «Иван Чепиков» can still co-rank via bigrams + shared neighbours). */
export const nameSim = (a: string, b: string): number =>
  Math.max(jaccard(a, b) * 0.85, bigramDice(a, b) * 0.75);

/** nodeId → set of adjacent node ids (any edge type, undirected). */
export function neighbourMap(state: GraphState): Map<Id, Set<Id>> {
  const m = new Map<Id, Set<Id>>();
  const add = (a: Id, b: Id) => {
    let s = m.get(a);
    if (!s) m.set(a, (s = new Set()));
    s.add(b);
  };
  for (const e of state.edges) {
    add(e.sourceId, e.targetId);
    add(e.targetId, e.sourceId);
  }
  return m;
}

export const degreeMap = (state: GraphState): Map<Id, number> => {
  const m = new Map<Id, number>();
  for (const e of state.edges) {
    m.set(e.sourceId, (m.get(e.sourceId) ?? 0) + 1);
    m.set(e.targetId, (m.get(e.targetId) ?? 0) + 1);
  }
  return m;
};

export function sharedNeighbours(
  nbr: Map<Id, Set<Id>>,
  a: Id,
  b: Id,
): number {
  const A = nbr.get(a);
  const B = nbr.get(b);
  if (!A || !B) return 0;
  const [small, big] = A.size < B.size ? [A, B] : [B, A];
  let n = 0;
  for (const x of small) if (big.has(x)) n++;
  return n;
}
