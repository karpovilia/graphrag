from __future__ import annotations

import pytest

from api.curation import (
    JournalApplyError,
    affected_set,
    apply_journal_op,
    parse_payload,
    replay_journal,
)
from api.domain.curation import JournalEntry, JournalOp
from api.domain.graph import Edge, EdgeType, Layer, Node
from api.domain.types import Id, new_id
from api.strategies.state import GraphBuildState


def _node(name: str, *, gv: Id, layer: Layer = Layer.ENTITY, type_: str = "PERSON") -> Node:
    return Node(graph_variant_id=gv, layer=layer, type=type_, granularity=1, name=name)


def _edge(
    src: Id,
    tgt: Id,
    *,
    gv: Id,
    type_: EdgeType = EdgeType.ENTITY_RELATION,
    weight: float | None = 1.0,
) -> Edge:
    return Edge(graph_variant_id=gv, type=type_, source_node_id=src, target_node_id=tgt, weight=weight)


def _entry(gv: Id, op: JournalOp, payload: dict) -> JournalEntry:
    return JournalEntry(
        graph_variant_id=gv, op=op, payload=payload, actor="user:test"
    )


# ---- merge_nodes ----


def test_merge_nodes_drops_absorbed_and_redirects_edges() -> None:
    gv = new_id()
    survivor = _node("Иванов А.", gv=gv)
    absorbed = _node("Иванов И.", gv=gv)
    other = _node("Петров", gv=gv)
    state = GraphBuildState(
        nodes=[survivor, absorbed, other],
        edges=[
            _edge(absorbed.id, other.id, gv=gv, weight=0.5),
            _edge(survivor.id, other.id, gv=gv, weight=0.9),
        ],
    )

    entry = _entry(
        gv,
        JournalOp.MERGE_NODES,
        {"survivor_id": str(survivor.id), "absorbed_ids": [str(absorbed.id)]},
    )
    out = apply_journal_op(state, entry)

    assert {n.id for n in out.nodes} == {survivor.id, other.id}
    # Two edges to `other` collapse into one after the redirect.
    assert len(out.edges) == 1
    assert out.edges[0].source_node_id == survivor.id
    assert out.journal[-1] is entry


def test_merge_nodes_rejects_survivor_in_absorbed() -> None:
    gv = new_id()
    a = _node("a", gv=gv)
    state = GraphBuildState(nodes=[a], edges=[])

    entry = _entry(
        gv,
        JournalOp.MERGE_NODES,
        {"survivor_id": str(a.id), "absorbed_ids": [str(a.id)]},
    )
    with pytest.raises(JournalApplyError):
        apply_journal_op(state, entry)


# ---- update_node_name + set_summary + retype_node ----


def test_update_node_name_changes_only_target() -> None:
    gv = new_id()
    a, b = _node("A", gv=gv), _node("B", gv=gv)
    state = GraphBuildState(nodes=[a, b], edges=[])
    entry = _entry(
        gv, JournalOp.UPDATE_NODE_NAME, {"node_id": str(a.id), "name": "A прим."}
    )

    out = apply_journal_op(state, entry)
    by_id = {n.id: n for n in out.nodes}
    assert by_id[a.id].name == "A прим."
    assert by_id[b.id].name == "B"


def test_set_summary_clears_when_null() -> None:
    gv = new_id()
    a = _node("A", gv=gv)
    state = GraphBuildState(
        nodes=[a.model_copy(update={"summary": "old"})], edges=[]
    )
    entry = _entry(gv, JournalOp.SET_SUMMARY, {"node_id": str(a.id), "summary": None})

    out = apply_journal_op(state, entry)
    assert out.nodes[0].summary is None


def test_retype_node() -> None:
    gv = new_id()
    a = _node("A", gv=gv, type_="PERSON")
    state = GraphBuildState(nodes=[a], edges=[])
    entry = _entry(
        gv,
        JournalOp.RETYPE_NODE,
        {"node_id": str(a.id), "new_type": "ORG", "old_type": "PERSON"},
    )

    out = apply_journal_op(state, entry)
    assert out.nodes[0].type == "ORG"


def test_update_unknown_node_raises() -> None:
    gv = new_id()
    state = GraphBuildState(nodes=[], edges=[])
    entry = _entry(
        gv, JournalOp.UPDATE_NODE_NAME, {"node_id": str(new_id()), "name": "x"}
    )
    with pytest.raises(JournalApplyError):
        apply_journal_op(state, entry)


# ---- edge ops ----


def test_add_and_delete_edge_round_trip() -> None:
    gv = new_id()
    a, b = _node("a", gv=gv), _node("b", gv=gv)
    state = GraphBuildState(nodes=[a, b], edges=[])

    add_entry = _entry(
        gv,
        JournalOp.ADD_EDGE,
        {
            "edge": {
                "graph_variant_id": str(gv),
                "type": "entity_relation",
                "source_node_id": str(a.id),
                "target_node_id": str(b.id),
                "weight": 0.7,
            }
        },
    )
    after_add = apply_journal_op(state, add_entry)
    assert len(after_add.edges) == 1
    new_edge = after_add.edges[0]

    delete_entry = _entry(
        gv, JournalOp.DELETE_EDGE, {"edge_id": str(new_edge.id)}
    )
    after_delete = apply_journal_op(after_add, delete_entry)
    assert after_delete.edges == []


def test_delete_edge_with_reason_soft_invalidates() -> None:
    """DELETE_EDGE *with* a reason is a soft delete (§1.4): the edge stays
    in state but gets tx_to + an EdgeInvalidation stamped, instead of
    being dropped. This is what feeds diff().invalidated and keeps the
    edge revert-eligible (R2 §2.4)."""
    gv = new_id()
    a, b = _node("a", gv=gv), _node("b", gv=gv)
    e = _edge(a.id, b.id, gv=gv)
    state = GraphBuildState(nodes=[a, b], edges=[e])

    entry = _entry(
        gv,
        JournalOp.DELETE_EDGE,
        {"edge_id": str(e.id), "reason": "superseded by ingest"},
    )
    after = apply_journal_op(state, entry)
    # Edge survives, now carrying invalidation provenance.
    assert len(after.edges) == 1
    survived = after.edges[0]
    assert survived.id == e.id
    assert survived.tx_to is not None
    assert survived.invalidation is not None
    assert survived.invalidation.reason == "superseded by ingest"
    # actor "user:test" → manual curation, not auto.
    assert survived.invalidation.auto is False
    assert survived.tx_to == survived.invalidation.at


def test_delete_edge_with_superseded_at_and_event_link() -> None:
    """superseded_at (filled by the route) sets tx_to/invalidation.at, and
    ingestion_event_id is threaded into the invalidation record. An
    `agent:` actor marks the invalidation auto=True."""
    from datetime import datetime, timezone

    gv = new_id()
    a, b = _node("a", gv=gv), _node("b", gv=gv)
    e = _edge(a.id, b.id, gv=gv)
    state = GraphBuildState(nodes=[a, b], edges=[e])
    at = datetime(2024, 5, 20, tzinfo=timezone.utc)
    ev_id = new_id()

    entry = JournalEntry(
        graph_variant_id=gv,
        op=JournalOp.DELETE_EDGE,
        payload={
            "edge_id": str(e.id),
            "reason": "superseded by Эпизод 3",
            "ingestion_event_id": str(ev_id),
            "superseded_at": at.isoformat(),
        },
        actor="agent:ingestion",
    )
    after = apply_journal_op(state, entry)
    survived = after.edges[0]
    assert survived.tx_to == at
    assert survived.invalidation.at == at
    assert survived.invalidation.ingestion_event_id == ev_id
    assert survived.invalidation.auto is True


def test_delete_edge_without_reason_hard_deletes() -> None:
    """No reason → legacy hard delete (back-compat)."""
    gv = new_id()
    a, b = _node("a", gv=gv), _node("b", gv=gv)
    e = _edge(a.id, b.id, gv=gv)
    state = GraphBuildState(nodes=[a, b], edges=[e])

    entry = _entry(gv, JournalOp.DELETE_EDGE, {"edge_id": str(e.id)})
    after = apply_journal_op(state, entry)
    assert after.edges == []


def test_delete_node_with_reason_applies() -> None:
    """DeleteNodePayload accepts optional `reason` without breaking apply."""
    gv = new_id()
    a, b = _node("a", gv=gv), _node("b", gv=gv)
    e = _edge(a.id, b.id, gv=gv)
    state = GraphBuildState(nodes=[a, b], edges=[e])

    entry = _entry(
        gv,
        JournalOp.DELETE_NODE,
        {"node_id": str(a.id), "reason": "merged elsewhere"},
    )
    after = apply_journal_op(state, entry)
    assert [n.id for n in after.nodes] == [b.id]
    assert after.edges == []  # edge touching a is dropped


def test_edit_edge_rejects_unknown_field() -> None:
    gv = new_id()
    a, b = _node("a", gv=gv), _node("b", gv=gv)
    e = _edge(a.id, b.id, gv=gv)
    state = GraphBuildState(nodes=[a, b], edges=[e])

    entry = _entry(
        gv,
        JournalOp.EDIT_EDGE,
        {"edge_id": str(e.id), "updates": {"bogus_field": 1}},
    )
    with pytest.raises(JournalApplyError):
        apply_journal_op(state, entry)


def test_edit_edge_updates_weight_and_relation() -> None:
    gv = new_id()
    a, b = _node("a", gv=gv), _node("b", gv=gv)
    e = _edge(a.id, b.id, gv=gv, weight=0.5)
    state = GraphBuildState(nodes=[a, b], edges=[e])

    entry = _entry(
        gv,
        JournalOp.EDIT_EDGE,
        {
            "edge_id": str(e.id),
            "updates": {"weight": 0.9, "relation": "works_at"},
        },
    )
    out = apply_journal_op(state, entry)
    assert out.edges[0].weight == 0.9
    assert out.edges[0].relation == "works_at"


# ---- move_to_community ----


def test_move_to_community_replaces_member_of_edge() -> None:
    gv = new_id()
    entity = _node("E", gv=gv)
    old_community = _node("c_old", gv=gv, layer=Layer.COMMUNITY, type_="COMMUNITY")
    new_community = _node("c_new", gv=gv, layer=Layer.COMMUNITY, type_="COMMUNITY")
    member_edge = _edge(
        entity.id, old_community.id, gv=gv, type_=EdgeType.MEMBER_OF, weight=None
    )
    state = GraphBuildState(
        nodes=[entity, old_community, new_community], edges=[member_edge]
    )

    entry = _entry(
        gv,
        JournalOp.MOVE_TO_COMMUNITY,
        {
            "node_id": str(entity.id),
            "to_community_id": str(new_community.id),
            "from_community_id": str(old_community.id),
        },
    )
    out = apply_journal_op(state, entry)

    member_edges = [e for e in out.edges if e.type == EdgeType.MEMBER_OF]
    assert len(member_edges) == 1
    assert member_edges[0].target_node_id == new_community.id


# ---- replay ----


def test_replay_applies_in_order() -> None:
    gv = new_id()
    a, b, c = _node("A", gv=gv), _node("B", gv=gv), _node("C", gv=gv)
    state = GraphBuildState(nodes=[a, b, c], edges=[])

    rename = _entry(
        gv, JournalOp.UPDATE_NODE_NAME, {"node_id": str(a.id), "name": "A1"}
    )
    rename_again = _entry(
        gv, JournalOp.UPDATE_NODE_NAME, {"node_id": str(a.id), "name": "A2"}
    )

    out = replay_journal(state, [rename, rename_again])
    by_id = {n.id: n for n in out.nodes}
    assert by_id[a.id].name == "A2"
    assert len(out.journal) == 2


# ---- affected_set ----


def test_affected_set_merge_includes_all_touched_and_community() -> None:
    gv = new_id()
    survivor = _node("s", gv=gv)
    absorbed = _node("a", gv=gv)
    community = _node("c", gv=gv, layer=Layer.COMMUNITY, type_="COMMUNITY")
    member = _edge(
        absorbed.id, community.id, gv=gv, type_=EdgeType.MEMBER_OF, weight=None
    )
    state = GraphBuildState(
        nodes=[survivor, absorbed, community], edges=[member]
    )
    entry = _entry(
        gv,
        JournalOp.MERGE_NODES,
        {"survivor_id": str(survivor.id), "absorbed_ids": [str(absorbed.id)]},
    )

    eff = affected_set(state, entry)
    assert eff.node_ids == frozenset({survivor.id, absorbed.id})
    assert community.id in eff.community_ids


def test_affected_set_rename_only_node() -> None:
    gv = new_id()
    a = _node("a", gv=gv)
    state = GraphBuildState(nodes=[a], edges=[])
    entry = _entry(
        gv, JournalOp.UPDATE_NODE_NAME, {"node_id": str(a.id), "name": "A"}
    )

    eff = affected_set(state, entry)
    assert eff.node_ids == frozenset({a.id})
    assert eff.community_ids == frozenset()
    assert eff.edge_ids == frozenset()


def test_affected_set_move_includes_both_communities() -> None:
    gv = new_id()
    e = _node("E", gv=gv)
    c_old = _node("c1", gv=gv, layer=Layer.COMMUNITY, type_="COMMUNITY")
    c_new = _node("c2", gv=gv, layer=Layer.COMMUNITY, type_="COMMUNITY")
    member = _edge(e.id, c_old.id, gv=gv, type_=EdgeType.MEMBER_OF, weight=None)
    state = GraphBuildState(nodes=[e, c_old, c_new], edges=[member])

    entry = _entry(
        gv,
        JournalOp.MOVE_TO_COMMUNITY,
        {"node_id": str(e.id), "to_community_id": str(c_new.id)},
    )
    eff = affected_set(state, entry)
    assert eff.community_ids == frozenset({c_old.id, c_new.id})


# ---- payload validation ----


def test_parse_payload_accepts_correct_shape() -> None:
    payload = parse_payload(
        JournalOp.MERGE_NODES,
        {"survivor_id": str(new_id()), "absorbed_ids": [str(new_id())]},
    )
    assert payload.absorbed_ids


def test_parse_payload_rejects_wrong_shape() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        parse_payload(JournalOp.MERGE_NODES, {"absorbed_ids": []})  # missing survivor_id
