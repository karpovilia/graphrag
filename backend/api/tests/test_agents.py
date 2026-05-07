from __future__ import annotations

import pytest

from api.agents import (
    CommunityStabilityScout,
    EntityDeduplicator,
    LowConfidenceTriplet,
    OrphanRescuer,
    RelationConsistencyChecker,
    TopicReportRefresher,
)
from api.domain.curation import (
    JournalEntry,
    JournalOp,
    SuggestionAction,
    SuggestionStatus,
)
from api.domain.graph import Edge, EdgeType, Layer, Node
from api.domain.types import Id, new_id
from api.strategies.state import GraphBuildState


def _node(name: str, gv: Id, *, layer: Layer = Layer.ENTITY, **kw) -> Node:
    return Node(
        graph_variant_id=gv,
        layer=layer,
        type=kw.pop("type_", "PERSON"),
        granularity=kw.pop("granularity", 1),
        name=name,
        **kw,
    )


def _entity_relation(src: Id, tgt: Id, gv: Id, *, weight: float | None = 1.0) -> Edge:
    return Edge(
        graph_variant_id=gv,
        type=EdgeType.ENTITY_RELATION,
        source_node_id=src,
        target_node_id=tgt,
        weight=weight,
    )


def _member_of(node_id: Id, community_id: Id, gv: Id) -> Edge:
    return Edge(
        graph_variant_id=gv,
        type=EdgeType.MEMBER_OF,
        source_node_id=node_id,
        target_node_id=community_id,
    )


# ---- EntityDeduplicator ----


async def test_entity_dedup_groups_by_lemma_attribute() -> None:
    gv = new_id()
    a = _node("Иванов", gv, attributes={"lemma": "иванов"})
    b = _node("Иванова", gv, attributes={"lemma": "иванов"}, summary="lead")
    other = _node("Петров", gv, attributes={"lemma": "петров"})
    state = GraphBuildState(nodes=[a, b, other], edges=[])

    suggestions = await EntityDeduplicator().propose(gv, state, {})

    assert len(suggestions) == 1
    s = suggestions[0]
    assert s.action == SuggestionAction.MERGE
    # Survivor is the longer-summary node (b).
    assert s.payload["survivor_id"] == str(b.id)
    assert str(a.id) in s.payload["absorbed_ids"]
    assert s.status == SuggestionStatus.PENDING
    assert s.confidence == 0.95


async def test_entity_dedup_falls_back_to_first_token_when_no_lemma() -> None:
    gv = new_id()
    a = _node("Иванов И.", gv)
    b = _node("Иванов А.", gv)
    state = GraphBuildState(nodes=[a, b], edges=[])

    suggestions = await EntityDeduplicator().propose(gv, state, {})
    assert len(suggestions) == 1
    assert suggestions[0].action == SuggestionAction.MERGE


async def test_entity_dedup_respects_type_boundary() -> None:
    gv = new_id()
    person = _node("Иванов", gv, type_="PERSON", attributes={"lemma": "иванов"})
    org = _node("Иванов", gv, type_="ORG", attributes={"lemma": "иванов"})
    state = GraphBuildState(nodes=[person, org], edges=[])

    assert await EntityDeduplicator().propose(gv, state, {}) == []


async def test_entity_dedup_caps_via_max_suggestions() -> None:
    gv = new_id()
    nodes = []
    for lemma in ("a", "b", "c"):
        nodes.extend([_node(f"{lemma}{i}", gv, attributes={"lemma": lemma}) for i in range(2)])
    state = GraphBuildState(nodes=nodes, edges=[])

    suggestions = await EntityDeduplicator().propose(
        gv, state, {"max_suggestions": 2}
    )
    assert len(suggestions) == 2


# ---- OrphanRescuer ----


async def test_orphan_rescuer_flags_zero_degree_entities() -> None:
    gv = new_id()
    isolated = _node("Иванов", gv)
    connected_a = _node("Петров", gv)
    connected_b = _node("Сидоров", gv)
    state = GraphBuildState(
        nodes=[isolated, connected_a, connected_b],
        edges=[_entity_relation(connected_a.id, connected_b.id, gv)],
    )

    suggestions = await OrphanRescuer().propose(gv, state, {})
    flagged_ids = {s.target_node_ids[0] for s in suggestions}
    assert flagged_ids == {isolated.id}


async def test_orphan_rescuer_threshold_keeps_low_degree_nodes() -> None:
    gv = new_id()
    a = _node("A", gv)
    b = _node("B", gv)
    state = GraphBuildState(nodes=[a, b], edges=[_entity_relation(a.id, b.id, gv)])

    # threshold=1 → degree-1 nodes are NOT orphans
    assert await OrphanRescuer().propose(gv, state, {"min_total_degree_to_skip": 1}) == []
    # threshold=2 → both nodes are orphans
    suggestions = await OrphanRescuer().propose(
        gv, state, {"min_total_degree_to_skip": 2}
    )
    assert len(suggestions) == 2


# ---- LowConfidenceTriplet ----


async def test_low_confidence_triplet_flags_below_threshold() -> None:
    gv = new_id()
    a, b, c = _node("a", gv), _node("b", gv), _node("c", gv)
    weak = _entity_relation(a.id, b.id, gv, weight=0.1)
    strong = _entity_relation(b.id, c.id, gv, weight=0.9)
    state = GraphBuildState(nodes=[a, b, c], edges=[weak, strong])

    suggestions = await LowConfidenceTriplet().propose(
        gv, state, {"weight_threshold": 0.3}
    )
    assert len(suggestions) == 1
    assert suggestions[0].target_edge_ids == [weak.id]
    assert suggestions[0].confidence > 0.5


async def test_low_confidence_triplet_skips_unweighted() -> None:
    gv = new_id()
    a, b = _node("a", gv), _node("b", gv)
    state = GraphBuildState(
        nodes=[a, b], edges=[_entity_relation(a.id, b.id, gv, weight=None)]
    )

    assert await LowConfidenceTriplet().propose(gv, state, {}) == []


async def test_low_confidence_triplet_orders_weakest_first() -> None:
    gv = new_id()
    a, b, c, d = _node("a", gv), _node("b", gv), _node("c", gv), _node("d", gv)
    e1 = _entity_relation(a.id, b.id, gv, weight=0.05)
    e2 = _entity_relation(b.id, c.id, gv, weight=0.2)
    e3 = _entity_relation(c.id, d.id, gv, weight=0.25)
    state = GraphBuildState(nodes=[a, b, c, d], edges=[e1, e2, e3])

    suggestions = await LowConfidenceTriplet().propose(
        gv, state, {"weight_threshold": 0.3, "max_suggestions": 2}
    )
    flagged = [s.target_edge_ids[0] for s in suggestions]
    assert flagged == [e1.id, e2.id]


# ---- TopicReportRefresher ----


async def test_topic_refresher_flags_communities_after_merge() -> None:
    gv = new_id()
    survivor = _node("s", gv)
    absorbed = _node("a", gv)
    community = _node("c", gv, layer=Layer.COMMUNITY, type_="COMMUNITY")
    member_a = _member_of(absorbed.id, community.id, gv)
    member_s = _member_of(survivor.id, community.id, gv)

    journal_entry = JournalEntry(
        graph_variant_id=gv,
        op=JournalOp.MERGE_NODES,
        payload={
            "survivor_id": str(survivor.id),
            "absorbed_ids": [str(absorbed.id)],
        },
        actor="user:t",
    )

    state = GraphBuildState(
        nodes=[survivor, absorbed, community],
        edges=[member_a, member_s],
        journal=[journal_entry],
    )

    suggestions = await TopicReportRefresher().propose(gv, state, {})
    assert len(suggestions) == 1
    assert suggestions[0].target_node_ids == [community.id]
    assert "stale" in suggestions[0].payload["summary_status"]


async def test_topic_refresher_no_op_without_shift_journal() -> None:
    gv = new_id()
    a = _node("a", gv)
    community = _node("c", gv, layer=Layer.COMMUNITY, type_="COMMUNITY")
    state = GraphBuildState(
        nodes=[a, community],
        edges=[_member_of(a.id, community.id, gv)],
    )

    assert await TopicReportRefresher().propose(gv, state, {}) == []


async def test_topic_refresher_returns_empty_without_communities() -> None:
    gv = new_id()
    a = _node("a", gv)
    state = GraphBuildState(nodes=[a], edges=[], journal=[])
    assert await TopicReportRefresher().propose(gv, state, {}) == []


# ---- Stub agents ----


@pytest.mark.parametrize(
    "cls,name",
    [
        (RelationConsistencyChecker, "relation_consistency"),
        (CommunityStabilityScout, "community_stability"),
    ],
)
async def test_stub_agents_have_descriptors_and_raise(cls, name) -> None:
    assert cls.descriptor.kind == "agent"
    assert cls.descriptor.name == name
    with pytest.raises(NotImplementedError):
        await cls().propose(new_id(), GraphBuildState(), {})


# ---- Registry ----


def test_all_six_agents_registered() -> None:
    from api.strategies.registry import agents

    assert set(agents.names()) >= {
        "entity_dedup",
        "orphan_rescuer",
        "low_confidence_triplet",
        "topic_report_refresher",
        "relation_consistency",
        "community_stability",
    }
