/** Dependency-free Louvain community detection (modularity optimization with
 *  multi-level aggregation). graphrag uses Leiden (igraph/leidenalg, Python-
 *  only); per plan.md's locked deviation we use Louvain in the TS stack.
 *
 *  Operates on an undirected weighted graph and returns a membership map
 *  (original node id → community index). Deterministic: nodes are processed
 *  in input order and communities renumbered by first appearance, so repeated
 *  builds and git diffs are stable. */
export interface LouvainEdge {
  a: string;
  b: string;
  w: number;
}

interface Level {
  // adjacency[i] = Map<neighbor, weight>; selfLoop[i] = intra-node weight
  adj: Map<number, number>[];
  selfLoop: number[];
}

function oneLevel(level: Level, resolution: number): number[] {
  const { adj, selfLoop } = level;
  const n = adj.length;
  const degree = new Array<number>(n).fill(0);
  for (let i = 0; i < n; i++) {
    let d = selfLoop[i]! * 2;
    for (const w of adj[i]!.values()) d += w;
    degree[i] = d;
  }
  const m = Math.max(1e-9, degree.reduce((a, b) => a + b, 0) / 2);

  const comm = Array.from({ length: n }, (_, i) => i);
  const commTot = degree.slice();

  let moved = true;
  while (moved) {
    moved = false;
    for (let i = 0; i < n; i++) {
      const ci = comm[i]!;
      // weight from i into each neighbouring community
      const links = new Map<number, number>();
      links.set(ci, 0);
      for (const [j, w] of adj[i]!) {
        const cj = comm[j]!;
        links.set(cj, (links.get(cj) ?? 0) + w);
      }
      // pull i out of its community
      commTot[ci] = commTot[ci]! - degree[i]!;

      let best = ci;
      let bestGain = 0;
      for (const [c, kIn] of links) {
        const gain = kIn - (resolution * commTot[c]! * degree[i]!) / (2 * m);
        if (gain > bestGain + 1e-12) {
          bestGain = gain;
          best = c;
        }
      }
      commTot[best] = commTot[best]! + degree[i]!;
      if (best !== ci) {
        comm[i] = best;
        moved = true;
      }
    }
  }
  return comm;
}

/** Renumber arbitrary community labels to 0..k-1 by first appearance. */
function renumber(labels: number[]): { labels: number[]; count: number } {
  const map = new Map<number, number>();
  const out = labels.map((l) => {
    let r = map.get(l);
    if (r === undefined) {
      r = map.size;
      map.set(l, r);
    }
    return r;
  });
  return { labels: out, count: map.size };
}

export function louvain(
  nodeIds: string[],
  edges: LouvainEdge[],
  opts: { resolution?: number; maxLevels?: number } = {},
): Map<string, number> {
  const resolution = opts.resolution ?? 1.0;
  const maxLevels = opts.maxLevels ?? 20;
  const n = nodeIds.length;
  const index = new Map(nodeIds.map((id, i) => [id, i]));

  // Build the level-0 graph.
  let adj: Map<number, number>[] = Array.from({ length: n }, () => new Map());
  let selfLoop = new Array<number>(n).fill(0);
  for (const { a, b, w } of edges) {
    const u = index.get(a);
    const v = index.get(b);
    if (u === undefined || v === undefined || !(w > 0)) continue;
    if (u === v) {
      selfLoop[u]! += w;
      continue;
    }
    adj[u]!.set(v, (adj[u]!.get(v) ?? 0) + w);
    adj[v]!.set(u, (adj[v]!.get(u) ?? 0) + w);
  }

  // original node → current super-node index
  let nodeToSuper = Array.from({ length: n }, (_, i) => i);

  for (let lvl = 0; lvl < maxLevels; lvl++) {
    const raw = oneLevel({ adj, selfLoop }, resolution);
    const { labels: comm, count } = renumber(raw);
    if (count === adj.length) break; // no merges → converged

    // remap originals through this level
    nodeToSuper = nodeToSuper.map((s) => comm[s]!);

    // aggregate communities into the next-level graph
    const nAdj: Map<number, number>[] = Array.from({ length: count }, () => new Map());
    const nSelf = new Array<number>(count).fill(0);
    for (let i = 0; i < adj.length; i++) {
      nSelf[comm[i]!]! += selfLoop[i]!;
      for (const [j, w] of adj[i]!) {
        if (i < j) continue; // count each undirected pair once
        const ci = comm[i]!;
        const cj = comm[j]!;
        if (ci === cj) nSelf[ci]! += w;
        else {
          nAdj[ci]!.set(cj, (nAdj[ci]!.get(cj) ?? 0) + w);
          nAdj[cj]!.set(ci, (nAdj[cj]!.get(ci) ?? 0) + w);
        }
      }
    }
    adj = nAdj;
    selfLoop = nSelf;
  }

  // Final renumber by first appearance for stable labels.
  const { labels } = renumber(nodeToSuper);
  return new Map(nodeIds.map((id, i) => [id, labels[i]!]));
}
