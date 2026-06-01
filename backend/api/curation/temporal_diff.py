"""Pure bi-temporal materialization + diff (§0 grammar).

`materialize_at(state, t, axis)` filters a GraphBuildState down to the
facts live at instant `t` under the chosen time axis. `temporal_diff`
runs `diff_states` over two materializations and classifies every
changed id into the §0 grammar buckets:

  born            — id present in B, absent in A
  dead            — id present in A, absent in B, *no* invalidation record
  invalidated     — id present in A, absent in B, *with* an EdgeInvalidation
  persisted       — id present in both, unchanged
  moved_community — node whose MEMBER_OF community target differs A→B

`dead` and `invalidated` are disjoint; every changed id maps to exactly
one bucket. Counts mirror the per-id lists.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from api.curation.applier import _community_of
from api.domain.graph import Edge, EdgeInvalidation, Node
from api.domain.temporal import TemporalDiff, TemporalDiffEntry
from api.domain.types import Id
from api.strategies.state import GraphBuildState

Axis = Literal["tx", "valid"]


def _live_at(obj: Node | Edge, t: datetime, axis: Axis) -> bool:
    """True iff `obj` is live at instant `t` under `axis`.

    tx-mode:    tx_from <= t AND (tx_to IS NULL OR t < tx_to)
    valid-mode: valid_from <= t AND (valid_to IS NULL OR t < valid_to)

    A row with a NULL `*_from` has no anchor on that axis and is excluded
    (legacy rows have no event-time; T-mode simply skips them, documented
    in the migration notes).
    """

    if axis == "tx":
        start, end = obj.tx_from, obj.tx_to
    else:
        start, end = obj.valid_from, obj.valid_to

    if start is None:
        return False
    if start > t:
        return False
    if end is not None and t >= end:
        return False
    return True


def materialize_at(
    state: GraphBuildState, t: datetime, axis: Axis
) -> GraphBuildState:
    """Return a state containing only the facts live at `t` under `axis`.

    Journal is carried through unchanged — callers that need a clean
    diff only look at nodes/edges.
    """

    nodes = [n for n in state.nodes if _live_at(n, t, axis)]
    edges = [e for e in state.edges if _live_at(e, t, axis)]
    return GraphBuildState(nodes=nodes, edges=edges, journal=list(state.journal))


def temporal_diff(
    state_a: GraphBuildState,
    state_b: GraphBuildState,
    *,
    axis: Axis,
    variant_id: Id,
    t_a: datetime,
    t_b: datetime,
) -> TemporalDiff:
    """Classify the A→B delta into the §0 grammar buckets.

    `state_a` / `state_b` are already materialized (callers pass the
    output of `materialize_at`). Reuses `diff_states` for the structural
    added/removed/changed breakdown.
    """

    # Lazy import to avoid the api.repository package init pulling this
    # module back in (circular import at collection time).
    from api.repository.diff import diff_states

    sd = diff_states(state_a, state_b)

    edges_a = {e.id: e for e in state_a.edges}
    edges_b = {e.id: e for e in state_b.edges}

    born: list[TemporalDiffEntry] = []
    dead: list[TemporalDiffEntry] = []
    persisted: list[TemporalDiffEntry] = []
    moved_community: list[TemporalDiffEntry] = []
    invalidated: list[TemporalDiffEntry] = []

    # ---- born ----
    for n in sd.nodes_added:
        born.append(TemporalDiffEntry(id=n.id, kind="node", state="born"))
    for e in sd.edges_added:
        born.append(TemporalDiffEntry(id=e.id, kind="edge", state="born"))

    # ---- dead vs invalidated ----
    for nid in sd.nodes_removed:
        dead.append(TemporalDiffEntry(id=nid, kind="node", state="dead"))
    for eid in sd.edges_removed:
        # The invalidation record lives on the A-side edge (it is the one
        # that carries the provenance of *why* it vanished).
        inv = _edge_invalidation(edges_a.get(eid))
        if inv is not None:
            invalidated.append(
                TemporalDiffEntry(
                    id=eid,
                    kind="edge",
                    state="invalidated",
                    invalidation=inv,
                )
            )
        else:
            dead.append(TemporalDiffEntry(id=eid, kind="edge", state="dead"))

    # ---- persisted + moved_community (nodes present in both) ----
    nodes_a_ids = {n.id for n in state_a.nodes}
    nodes_b_ids = {n.id for n in state_b.nodes}
    for nid in nodes_a_ids & nodes_b_ids:
        from_c = _community_of(nid, state_a)
        to_c = _community_of(nid, state_b)
        if from_c != to_c:
            moved_community.append(
                TemporalDiffEntry(
                    id=nid,
                    kind="node",
                    state="moved_community",
                    from_community_id=from_c,
                    to_community_id=to_c,
                )
            )
        else:
            persisted.append(
                TemporalDiffEntry(id=nid, kind="node", state="persisted")
            )

    # ---- persisted edges (present in both) ----
    for eid in edges_a.keys() & edges_b.keys():
        persisted.append(TemporalDiffEntry(id=eid, kind="edge", state="persisted"))

    counts = {
        "born": len(born),
        "dead": len(dead),
        "persisted": len(persisted),
        "moved_community": len(moved_community),
        "invalidated": len(invalidated),
    }

    return TemporalDiff(
        variant_id=variant_id,
        axis=axis,
        t_a=t_a,
        t_b=t_b,
        born=born,
        dead=dead,
        persisted=persisted,
        moved_community=moved_community,
        invalidated=invalidated,
        counts=counts,
    )


def _edge_invalidation(edge: Edge | None) -> EdgeInvalidation | None:
    if edge is None:
        return None
    return edge.invalidation
