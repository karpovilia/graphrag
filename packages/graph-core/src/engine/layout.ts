import type { Id } from "../domain/types.js";
import type { GraphState } from "./state.js";

/** Deterministic, dependency-free force layout (Fruchterman–Reingold).
 *  Run once at import to give the render engine seed x/y positions; the
 *  client can still re-simulate. Deterministic (seeded) so re-imports and
 *  git diffs are stable. */

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const hash = (s: string): number => {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
};

export interface LayoutOptions {
  iterations?: number;
  width?: number;
  height?: number;
  seed?: number;
}

/** Compute (x,y) for every node. Returns a map id → position. */
export function computeLayout(
  state: GraphState,
  opts: LayoutOptions = {},
): Map<Id, { x: number; y: number }> {
  const nodes = state.nodes;
  const n = nodes.length;
  const W = opts.width ?? Math.max(800, Math.sqrt(n) * 120);
  const H = opts.height ?? W;
  const iterations = opts.iterations ?? (n > 1500 ? 120 : 200);
  const rng = mulberry32(opts.seed ?? hash(nodes[0]?.graphId ?? "g"));

  const pos = new Map<Id, { x: number; y: number }>();
  for (const node of nodes) {
    pos.set(node.id, { x: (rng() - 0.5) * W, y: (rng() - 0.5) * H });
  }
  if (n <= 1) return pos;

  const area = W * H;
  const k = Math.sqrt(area / n); // ideal edge length
  const idx = new Map(nodes.map((node, i) => [node.id, i]));
  const adj: [number, number][] = [];
  for (const e of state.edges) {
    const a = idx.get(e.sourceId);
    const b = idx.get(e.targetId);
    if (a != null && b != null && a !== b) adj.push([a, b]);
  }
  const arr = nodes.map((node) => pos.get(node.id)!);
  const disp = arr.map(() => ({ x: 0, y: 0 }));

  let temp = W / 10;
  const cool = temp / (iterations + 1);

  for (let it = 0; it < iterations; it++) {
    for (let i = 0; i < n; i++) disp[i]!.x = disp[i]!.y = 0;
    // repulsion (O(n^2))
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let dx = arr[i]!.x - arr[j]!.x;
        let dy = arr[i]!.y - arr[j]!.y;
        let dist = Math.hypot(dx, dy) || 0.01;
        const rep = (k * k) / dist;
        dx /= dist;
        dy /= dist;
        disp[i]!.x += dx * rep;
        disp[i]!.y += dy * rep;
        disp[j]!.x -= dx * rep;
        disp[j]!.y -= dy * rep;
      }
    }
    // attraction along edges
    for (const [a, b] of adj) {
      let dx = arr[a]!.x - arr[b]!.x;
      let dy = arr[a]!.y - arr[b]!.y;
      const dist = Math.hypot(dx, dy) || 0.01;
      const att = (dist * dist) / k;
      dx /= dist;
      dy /= dist;
      disp[a]!.x -= dx * att;
      disp[a]!.y -= dy * att;
      disp[b]!.x += dx * att;
      disp[b]!.y += dy * att;
    }
    // apply with temperature cap
    for (let i = 0; i < n; i++) {
      const d = Math.hypot(disp[i]!.x, disp[i]!.y) || 0.01;
      arr[i]!.x += (disp[i]!.x / d) * Math.min(d, temp);
      arr[i]!.y += (disp[i]!.y / d) * Math.min(d, temp);
    }
    temp -= cool;
  }
  return pos;
}

/** Write computed positions back onto a state's nodes (returns new state). */
export function withLayout(state: GraphState, opts: LayoutOptions = {}): GraphState {
  const pos = computeLayout(state, opts);
  return {
    ...state,
    nodes: state.nodes.map((node) => {
      const p = pos.get(node.id);
      return p ? { ...node, x: p.x, y: p.y } : node;
    }),
  };
}

/** Seed a new node's position at the centroid of its neighbours (+ jitter),
 *  so merge/split results don't fly in from (0,0). */
export function seedNear(
  state: GraphState,
  neighbourIds: Id[],
  jitter = 30,
): { x: number; y: number } {
  const pts = neighbourIds
    .map((id) => state.nodes.find((n) => n.id === id))
    .filter((n): n is NonNullable<typeof n> => n != null && n.x != null && n.y != null);
  if (!pts.length) return { x: 0, y: 0 };
  const cx = pts.reduce((s, n) => s + (n.x ?? 0), 0) / pts.length;
  const cy = pts.reduce((s, n) => s + (n.y ?? 0), 0) / pts.length;
  return {
    x: cx + (Math.random() - 0.5) * jitter,
    y: cy + (Math.random() - 0.5) * jitter,
  };
}
