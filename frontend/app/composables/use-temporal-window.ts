// §2.1 temporal orchestration, lifted OUT of LayeredGraph so split-view
// panes can share one window (closes the no-temporal-window-observable
// gap). Owns: axis (T / T'), mode (instant | diff), t, [t_a, t_b],
// playing. Calls api.graphs.at / .diff and exposes:
//   - visibleNodeIds / visibleEdgeIds  (instant: shrink the graph, R1)
//   - deltaIndex                        (diff: §0 grammar Map<id,DeltaState>)
//   - lastDiff                          (counts → DeltaLegend chips)
// Debounced + cached per (variantId, axis, t / t_a|t_b). Headless — does
// no rendering; pages bind the scrubber to it.

import { useState } from "nuxt/app";
import { computed, ref, shallowRef } from "vue";

import type {
  Id,
  TemporalDiff,
  TimeAxis,
} from "@/entities/api";
import type { DeltaState } from "@/components/organisms/LayeredGraph/lib/delta";
import { useApi } from "@/lib/api-client";

export type TemporalMode = "instant" | "diff";

function diffToDeltaIndex(diff: TemporalDiff): Map<string, DeltaState> {
  const index = new Map<string, DeltaState>();
  for (const it of diff.persisted) index.set(String(it.id), "persisted");
  for (const it of diff.born) index.set(String(it.id), "born");
  for (const it of diff.dead) index.set(String(it.id), "dead");
  for (const it of diff.moved_community)
    index.set(String(it.id), "moved_community");
  // invalidated is disjoint from dead; render with its own state.
  for (const it of diff.invalidated) index.set(String(it.id), "invalidated");
  return index;
}

export function useTemporalWindow(variantId: Id) {
  const api = useApi();

  // useState keys are namespaced by variant so split panes on different
  // variants don't clobber each other, but a single page's two
  // LayeredGraph instances on the SAME variant share the window.
  const axis = useState<TimeAxis>(`tw:${variantId}:axis`, () => "tx");
  const mode = useState<TemporalMode>(`tw:${variantId}:mode`, () => "instant");
  const t = useState<string | null>(`tw:${variantId}:t`, () => null);
  const range = useState<[string, string] | null>(
    `tw:${variantId}:range`,
    () => null,
  );
  const playing = ref(false);

  const visibleNodeIds = shallowRef<Set<string> | null>(null);
  const visibleEdgeIds = shallowRef<Set<string> | null>(null);
  const deltaIndex = shallowRef<Map<string, DeltaState> | null>(null);
  const lastDiff = shallowRef<TemporalDiff | null>(null);
  const loading = ref(false);
  const error = ref<unknown>(null);

  // Tiny request cache so re-scrubbing to a prior instant is instant.
  const atCache = new Map<string, { nodes: Set<string>; edges: Set<string> }>();
  const diffCache = new Map<string, TemporalDiff>();

  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  async function goToInstant(value: string) {
    t.value = value;
    mode.value = "instant";
    deltaIndex.value = null;
    lastDiff.value = null;
    const key = `${variantId}|${axis.value}|${value}`;
    const cached = atCache.get(key);
    if (cached) {
      visibleNodeIds.value = cached.nodes;
      visibleEdgeIds.value = cached.edges;
      return;
    }
    loading.value = true;
    error.value = null;
    try {
      const snap = await api.graphs.at(variantId, value, axis.value);
      const nodes = new Set(snap.node_ids.map(String));
      const edges = new Set(snap.edge_ids.map(String));
      atCache.set(key, { nodes, edges });
      visibleNodeIds.value = nodes;
      visibleEdgeIds.value = edges;
    } catch (e) {
      error.value = e;
    } finally {
      loading.value = false;
    }
  }

  async function goToDiff(tA: string, tB: string) {
    range.value = [tA, tB];
    mode.value = "diff";
    visibleNodeIds.value = null;
    visibleEdgeIds.value = null;
    const key = `${variantId}|${axis.value}|${tA}|${tB}`;
    const cached = diffCache.get(key);
    if (cached) {
      lastDiff.value = cached;
      deltaIndex.value = diffToDeltaIndex(cached);
      return;
    }
    loading.value = true;
    error.value = null;
    try {
      const diff = await api.graphs.diff(variantId, tA, tB, axis.value);
      diffCache.set(key, diff);
      lastDiff.value = diff;
      deltaIndex.value = diffToDeltaIndex(diff);
    } catch (e) {
      error.value = e;
    } finally {
      loading.value = false;
    }
  }

  /** Debounced entry point the scrubber drives on drag. */
  function scrubTo(value: string | [string, string]) {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      debounceTimer = null;
      if (Array.isArray(value)) void goToDiff(value[0], value[1]);
      else void goToInstant(value);
    }, 120);
  }

  /** Clear the temporal overlay — back to the full, current graph. */
  function reset() {
    if (debounceTimer) clearTimeout(debounceTimer);
    t.value = null;
    range.value = null;
    visibleNodeIds.value = null;
    visibleEdgeIds.value = null;
    deltaIndex.value = null;
    lastDiff.value = null;
    playing.value = false;
  }

  /** Re-apply the current selection on the new axis (T ↔ T'). Callers
   * also re-fetch the timeline (different sort) at the page level. */
  function setAxis(next: TimeAxis) {
    if (next === axis.value) return;
    axis.value = next;
    // Invalidate caches — the same t means a different fact set per axis.
    atCache.clear();
    diffCache.clear();
    if (mode.value === "diff" && range.value)
      void goToDiff(range.value[0], range.value[1]);
    else if (t.value) void goToInstant(t.value);
  }

  const active = computed(
    () => visibleNodeIds.value !== null || deltaIndex.value !== null,
  );

  return {
    axis,
    mode,
    t,
    range,
    playing,
    visibleNodeIds,
    visibleEdgeIds,
    deltaIndex,
    lastDiff,
    loading,
    error,
    active,
    goToInstant,
    goToDiff,
    scrubTo,
    reset,
    setAxis,
  };
}
