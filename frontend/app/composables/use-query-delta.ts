// §2.2 bridge — ask wizard → graph/compare evidence subgraph.
//
// The ask wizard runs POST /api/reason/delta and stashes the evidence /
// total id sets here, keyed by variant_id, WITHOUT serializing them into
// the URL (keeps back-nav + chat-affordance untouched; the graph page
// reads ?queryDelta=1 as a flag only). The graph page turns the stash
// into a Map<id, DeltaState> via the §0 grammar: evidence lit (1.0),
// complement dimmed (0.18).

import { useState } from "nuxt/app";

import type { Id, QueryDeltaResponse } from "@/entities/api";
import type { DeltaState } from "@/components/organisms/LayeredGraph/lib/delta";

export type QueryDeltaEntry = {
  evidence_node_ids: Id[];
  evidence_edge_ids: Id[];
  total_node_ids: Id[];
  total_edge_ids: Id[];
};

export function useQueryDelta() {
  // variant_id → evidence subgraph. Per-pane (MoE compare reads its own).
  const byVariant = useState<Record<Id, QueryDeltaEntry>>(
    "query-delta:by-variant",
    () => ({}),
  );

  function setFromResponse(resp: QueryDeltaResponse) {
    byVariant.value = {
      ...byVariant.value,
      [resp.variant_id]: {
        evidence_node_ids: resp.evidence_node_ids,
        evidence_edge_ids: resp.evidence_edge_ids,
        total_node_ids: resp.total_node_ids,
        total_edge_ids: resp.total_edge_ids,
      },
    };
  }

  /** Clear everything — called on a fresh ask so a stale highlight from
   * the previous question doesn't leak onto the new graph. */
  function clear() {
    byVariant.value = {};
  }

  function entryFor(variantId: Id): QueryDeltaEntry | null {
    return byVariant.value[variantId] ?? null;
  }

  /** Build the §0 delta index for one variant: evidence ids → "evidence"
   * (lit), every other id in the total set → "dimmed". Returns null when
   * there's nothing stashed for this variant. */
  function buildDeltaIndex(variantId: Id): Map<string, DeltaState> | null {
    const entry = entryFor(variantId);
    if (!entry) return null;
    const index = new Map<string, DeltaState>();
    const evidence = new Set<string>([
      ...entry.evidence_node_ids.map(String),
      ...entry.evidence_edge_ids.map(String),
    ]);
    for (const id of [...entry.total_node_ids, ...entry.total_edge_ids]) {
      index.set(String(id), evidence.has(String(id)) ? "evidence" : "dimmed");
    }
    // Ensure evidence ids are present even if they weren't in total_*.
    for (const id of evidence) index.set(id, "evidence");
    return index;
  }

  return { byVariant, setFromResponse, clear, entryFor, buildDeltaIndex };
}
