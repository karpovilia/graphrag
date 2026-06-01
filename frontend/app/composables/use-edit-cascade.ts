// §2.3 edit-cascade — the single headless wrapper around EVERY
// journal-writing call so the cascade animation + latency feedback are
// uniform across NodeDrawer / SuggestionsSidebar / InvalidationPanel.
//
// Each write method (append / undo / accept / revert) flips `running`,
// calls the matching api.graphs.* / api.agents.* method, then reads the
// already-present `affected` set + `recompute_ms` off the
// JournalAppendResult (api.types.ts:350-357 — NO backend/contract
// change needed) to:
//   - publish lastTiming (drives the LatencyBadge), and
//   - kick a transient BFS "ripple" over the current edges so the
//     LayeredGraph paints the §0 'edit' delta source outward from the
//     touched nodes, then clears itself (~600ms, hop budget 3).
//
// reject() is deliberately NOT wrapped: it writes no journal entry and
// triggers no cascade, so it stays inline in SuggestionsSidebar.

import { ref, type Ref } from "vue";

import type {
  Edge,
  Id,
  JournalAppendRequest,
  JournalAppendResult,
} from "@/entities/api";
import type { DeltaState } from "@/components/organisms/LayeredGraph/lib/delta";
import { useApi } from "@/lib/api-client";

export type CascadeTiming = {
  recompute_ms: number;
  node_count_after: number;
  edge_count_after: number;
};

const RIPPLE_TOTAL_MS = 600;
const RIPPLE_HOPS = 3;
const RIPPLE_STEP_MS = RIPPLE_TOTAL_MS / RIPPLE_HOPS; // ~200ms / hop

/** Build an undirected adjacency map source<->target from the current
 * edges so the ripple can BFS outward from the affected nodes. */
function buildAdjacency(edges: Edge[]): Map<string, Set<string>> {
  const adj = new Map<string, Set<string>>();
  const link = (a: string, b: string) => {
    let set = adj.get(a);
    if (!set) {
      set = new Set<string>();
      adj.set(a, set);
    }
    set.add(b);
  };
  for (const e of edges) {
    const s = String(e.source_node_id);
    const t = String(e.target_node_id);
    link(s, t);
    link(t, s);
  }
  return adj;
}

export function useEditCascade(
  variantId: Id,
  /** Getter for the current edge set so the ripple BFS is always fresh
   * (the page passes `() => edges.value ?? []`). */
  edgesGetter: () => Edge[] = () => [],
) {
  const api = useApi();

  const running: Ref<boolean> = ref(false);
  const lastTiming: Ref<CascadeTiming | null> = ref(null);
  const error: Ref<unknown> = ref(null);
  const deltaIndex: Ref<Map<string, DeltaState> | null> = ref(null);
  const rippleActive: Ref<boolean> = ref(false);

  let timers: ReturnType<typeof setTimeout>[] = [];

  function stopRipple() {
    for (const tmr of timers) clearTimeout(tmr);
    timers = [];
    rippleActive.value = false;
    deltaIndex.value = null;
  }

  /** Transient BFS ripple. Hop-0 = affected node ids (seeded with their
   * known state, else 'evidence'); each subsequent hop tags newly-reached
   * ids as 'evidence' with decreasing visual weight (alpha handled by the
   * §0 grammar). Clears back to null on completion — the cascade is
   * ephemeral, nothing is cached. */
  function runRipple(seedStates: Map<string, DeltaState>) {
    stopRipple();
    const edges = edgesGetter();
    const adj = buildAdjacency(edges);

    const index = new Map<string, DeltaState>();
    const visited = new Set<string>();
    let frontier: string[] = [];
    for (const [id, state] of seedStates) {
      index.set(id, state ?? "evidence");
      visited.add(id);
      frontier.push(id);
    }

    rippleActive.value = true;
    deltaIndex.value = new Map(index);

    for (let hop = 1; hop <= RIPPLE_HOPS; hop++) {
      const tmr = setTimeout(() => {
        const next: string[] = [];
        for (const id of frontier) {
          const neighbours = adj.get(id);
          if (!neighbours) continue;
          for (const nb of neighbours) {
            if (visited.has(nb)) continue;
            visited.add(nb);
            index.set(nb, "evidence");
            next.push(nb);
          }
        }
        frontier = next;
        deltaIndex.value = new Map(index);
      }, RIPPLE_STEP_MS * hop);
      timers.push(tmr);
    }

    // After the full window, clear so the overlay is transient.
    const done = setTimeout(stopRipple, RIPPLE_TOTAL_MS + RIPPLE_STEP_MS);
    timers.push(done);
  }

  /** Translate a JournalAppendResult into lastTiming + a ripple. The
   * seed states come from the diff-grammar where known (born for added,
   * moved_community for moves) else 'evidence'. */
  function applyResult(result: JournalAppendResult) {
    lastTiming.value = {
      recompute_ms: result.recompute_ms,
      node_count_after: result.variant.node_count,
      edge_count_after: result.variant.edge_count,
    };
    const seeds = new Map<string, DeltaState>();
    for (const id of result.affected.node_ids) {
      seeds.set(String(id), "evidence");
    }
    // Edges touched but with no node anchor still ripple via their ids.
    for (const id of result.affected.edge_ids) {
      if (!seeds.has(String(id))) seeds.set(String(id), "evidence");
    }
    if (seeds.size) runRipple(seeds);
  }

  async function append(
    req: JournalAppendRequest,
  ): Promise<JournalAppendResult> {
    running.value = true;
    error.value = null;
    try {
      const result = await api.graphs.appendJournal(variantId, req);
      applyResult(result);
      return result;
    } catch (e) {
      error.value = e;
      throw e;
    } finally {
      running.value = false;
    }
  }

  async function undo(
    expected_version: number,
  ): Promise<JournalAppendResult> {
    running.value = true;
    error.value = null;
    try {
      const result = await api.graphs.undo(variantId, { expected_version });
      applyResult(result);
      return result;
    } catch (e) {
      error.value = e;
      throw e;
    } finally {
      running.value = false;
    }
  }

  async function accept(
    suggestionId: Id,
    opts: { expected_variant_version: number; actor: string },
  ): Promise<JournalAppendResult> {
    running.value = true;
    error.value = null;
    try {
      const result = await api.agents.accept(suggestionId, {
        expected_variant_version: opts.expected_variant_version,
        actor: opts.actor,
      });
      applyResult(result);
      return result;
    } catch (e) {
      error.value = e;
      throw e;
    } finally {
      running.value = false;
    }
  }

  async function revert(
    edgeId: Id,
    opts: { expected_version: number; actor: string },
  ): Promise<JournalAppendResult> {
    running.value = true;
    error.value = null;
    try {
      const result = await api.graphs.revertInvalidation(variantId, edgeId, {
        expected_version: opts.expected_version,
        actor: opts.actor,
      });
      applyResult(result);
      return result;
    } catch (e) {
      error.value = e;
      throw e;
    } finally {
      running.value = false;
    }
  }

  return {
    running,
    lastTiming,
    error,
    deltaIndex,
    rippleActive,
    append,
    undo,
    accept,
    revert,
    stopRipple,
  };
}

export type EditCascade = ReturnType<typeof useEditCascade>;
