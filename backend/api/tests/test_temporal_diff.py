"""Unit tests for the pure bi-temporal materialize + diff (§0 grammar).

Deterministic, offline: hand-built GraphBuildStates with explicit
tx_*/valid_* stamps and one Edge.invalidation provenance record.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from api.curation.temporal_diff import materialize_at, temporal_diff
from api.domain.graph import Edge, EdgeInvalidation, EdgeType, Layer, Node
from api.domain.types import new_id
from api.strategies.state import GraphBuildState

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _t(days: int) -> datetime:
    return T0 + timedelta(days=days)


def _node(vid, *, tx_from=None, tx_to=None, valid_from=None, valid_to=None, layer=Layer.ENTITY):
    return Node(
        id=new_id(),
        graph_variant_id=vid,
        layer=layer,
        type="PERSON",
        granularity=1,
        name="n",
        tx_from=tx_from,
        tx_to=tx_to,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def _edge(vid, src, tgt, *, type=EdgeType.ENTITY_RELATION, tx_from=None, tx_to=None,
          valid_from=None, valid_to=None, invalidation=None):
    return Edge(
        id=new_id(),
        graph_variant_id=vid,
        type=type,
        source_node_id=src,
        target_node_id=tgt,
        tx_from=tx_from,
        tx_to=tx_to,
        valid_from=valid_from,
        valid_to=valid_to,
        invalidation=invalidation,
    )


# ---- materialize_at ----


def test_materialize_tx_inclusive_start_exclusive_end():
    vid = new_id()
    n_a = _node(vid, tx_from=_t(0), tx_to=_t(10))  # live [0,10)
    n_b = _node(vid, tx_from=_t(5), tx_to=None)  # live [5, ∞)
    state = GraphBuildState(nodes=[n_a, n_b], edges=[])

    # t == tx_from is inclusive
    at0 = materialize_at(state, _t(0), "tx")
    assert {n.id for n in at0.nodes} == {n_a.id}

    # both live mid-window
    at5 = materialize_at(state, _t(5), "tx")
    assert {n.id for n in at5.nodes} == {n_a.id, n_b.id}

    # t == tx_to is exclusive → n_a drops
    at10 = materialize_at(state, _t(10), "tx")
    assert {n.id for n in at10.nodes} == {n_b.id}


def test_materialize_valid_axis_independent_of_tx():
    vid = new_id()
    n = _node(vid, tx_from=_t(0), valid_from=_t(20), valid_to=None)
    state = GraphBuildState(nodes=[n], edges=[])

    # live on tx at t=5, but not on valid (valid_from=20)
    assert {x.id for x in materialize_at(state, _t(5), "tx").nodes} == {n.id}
    assert materialize_at(state, _t(5), "valid").nodes == []
    assert {x.id for x in materialize_at(state, _t(25), "valid").nodes} == {n.id}


def test_materialize_null_anchor_excluded():
    vid = new_id()
    # legacy row: no tx_from anchor → excluded on tx axis
    n = _node(vid, tx_from=None, valid_from=None)
    state = GraphBuildState(nodes=[n], edges=[])
    assert materialize_at(state, _t(5), "tx").nodes == []
    assert materialize_at(state, _t(5), "valid").nodes == []


# ---- temporal_diff buckets ----


def test_temporal_diff_born_dead_persisted():
    vid = new_id()
    persist = _node(vid, tx_from=_t(0), tx_to=None)
    dead = _node(vid, tx_from=_t(0), tx_to=_t(8))  # gone by t=10
    born = _node(vid, tx_from=_t(9), tx_to=None)  # appears by t=10
    state = GraphBuildState(nodes=[persist, dead, born], edges=[])

    a = materialize_at(state, _t(5), "tx")  # persist + dead
    b = materialize_at(state, _t(10), "tx")  # persist + born

    diff = temporal_diff(a, b, axis="tx", variant_id=vid, t_a=_t(5), t_b=_t(10))

    assert {e.id for e in diff.born} == {born.id}
    assert {e.id for e in diff.dead} == {dead.id}
    assert {e.id for e in diff.persisted} == {persist.id}
    assert diff.counts == {
        "born": 1,
        "dead": 1,
        "persisted": 1,
        "moved_community": 0,
        "invalidated": 0,
    }


def test_temporal_diff_dead_vs_invalidated_disjoint():
    vid = new_id()
    s = _node(vid, tx_from=_t(0), tx_to=None)
    tgt = _node(vid, tx_from=_t(0), tx_to=None)

    plain_dead = _edge(vid, s.id, tgt.id, tx_from=_t(0), tx_to=_t(8))
    inv = EdgeInvalidation(
        at=_t(8), reason="superseded by episode 13", superseded_by_edge_id=None, auto=True
    )
    invalidated = _edge(
        vid, s.id, tgt.id, tx_from=_t(0), tx_to=_t(8), invalidation=inv
    )
    state = GraphBuildState(nodes=[s, tgt], edges=[plain_dead, invalidated])

    a = materialize_at(state, _t(5), "tx")  # both edges live
    b = materialize_at(state, _t(10), "tx")  # both gone

    diff = temporal_diff(a, b, axis="tx", variant_id=vid, t_a=_t(5), t_b=_t(10))

    dead_ids = {e.id for e in diff.dead}
    inv_ids = {e.id for e in diff.invalidated}
    assert dead_ids == {plain_dead.id}
    assert inv_ids == {invalidated.id}
    # disjoint
    assert dead_ids.isdisjoint(inv_ids)
    # provenance carried through
    entry = diff.invalidated[0]
    assert entry.invalidation is not None
    assert entry.invalidation.reason == "superseded by episode 13"


def test_temporal_diff_moved_community():
    vid = new_id()
    person = _node(vid, tx_from=_t(0), tx_to=None)
    comm_a = _node(vid, tx_from=_t(0), tx_to=None, layer=Layer.COMMUNITY)
    comm_b = _node(vid, tx_from=_t(0), tx_to=None, layer=Layer.COMMUNITY)

    member_a = _edge(
        vid, person.id, comm_a.id, type=EdgeType.MEMBER_OF, tx_from=_t(0), tx_to=_t(8)
    )
    member_b = _edge(
        vid, person.id, comm_b.id, type=EdgeType.MEMBER_OF, tx_from=_t(9), tx_to=None
    )
    state = GraphBuildState(
        nodes=[person, comm_a, comm_b], edges=[member_a, member_b]
    )

    a = materialize_at(state, _t(5), "tx")  # member_a
    b = materialize_at(state, _t(10), "tx")  # member_b

    diff = temporal_diff(a, b, axis="tx", variant_id=vid, t_a=_t(5), t_b=_t(10))

    moved_ids = {e.id for e in diff.moved_community}
    assert person.id in moved_ids
    entry = next(e for e in diff.moved_community if e.id == person.id)
    assert entry.from_community_id == comm_a.id
    assert entry.to_community_id == comm_b.id
    # the community nodes themselves persist (membership edge change only)
    assert comm_a.id not in moved_ids
    assert comm_b.id not in moved_ids


def test_temporal_diff_one_to_one_id_state_mapping():
    """Every changed id maps to exactly one bucket / one entry."""
    vid = new_id()
    persist = _node(vid, tx_from=_t(0), tx_to=None)
    dead = _node(vid, tx_from=_t(0), tx_to=_t(8))
    born = _node(vid, tx_from=_t(9), tx_to=None)
    state = GraphBuildState(nodes=[persist, dead, born], edges=[])

    a = materialize_at(state, _t(5), "tx")
    b = materialize_at(state, _t(10), "tx")
    diff = temporal_diff(a, b, axis="tx", variant_id=vid, t_a=_t(5), t_b=_t(10))

    all_entries = (
        diff.born + diff.dead + diff.persisted + diff.moved_community + diff.invalidated
    )
    ids = [e.id for e in all_entries]
    assert len(ids) == len(set(ids))  # no id appears twice
