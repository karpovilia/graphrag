from __future__ import annotations

import pytest

from api.domain.graph import Edge, EdgeType, Layer, Node
from api.domain.types import Id, new_id
from api.strategies import GraphBuildState
from api.strategies.clusterers import LeidenClusterer


def _entity(name: str, gv: Id) -> Node:
    return Node(
        graph_variant_id=gv,
        layer=Layer.ENTITY,
        type="PERSON",
        granularity=1,
        name=name,
    )


def _entity_relation(src: Id, tgt: Id, gv: Id, *, weight: float = 1.0) -> Edge:
    return Edge(
        graph_variant_id=gv,
        type=EdgeType.ENTITY_RELATION,
        source_node_id=src,
        target_node_id=tgt,
        weight=weight,
    )


async def test_leiden_two_disconnected_cliques_split() -> None:
    gv = new_id()
    cluster_a = [_entity(f"a{i}", gv) for i in range(4)]
    cluster_b = [_entity(f"b{i}", gv) for i in range(4)]
    nodes = cluster_a + cluster_b

    edges: list[Edge] = []
    for grp in (cluster_a, cluster_b):
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                edges.append(_entity_relation(grp[i].id, grp[j].id, gv, weight=1.0))

    state = GraphBuildState(nodes=nodes, edges=edges)
    out = await LeidenClusterer().cluster(state, {"seed": 42})

    community_nodes = [n for n in out.nodes if n.layer == Layer.COMMUNITY]
    member_edges = [e for e in out.edges if e.type == EdgeType.MEMBER_OF]
    assert len(community_nodes) == 2
    assert len(member_edges) == len(nodes)

    # Each entity has exactly one MEMBER_OF edge to a community node.
    membership: dict[Id, Id] = {e.source_node_id: e.target_node_id for e in member_edges}
    a_communities = {membership[n.id] for n in cluster_a}
    b_communities = {membership[n.id] for n in cluster_b}
    assert len(a_communities) == 1
    assert len(b_communities) == 1
    assert a_communities != b_communities


async def test_leiden_re_run_replaces_existing_communities() -> None:
    gv = new_id()
    a, b = _entity("A", gv), _entity("B", gv)
    stale_community = Node(
        graph_variant_id=gv,
        layer=Layer.COMMUNITY,
        type="COMMUNITY",
        granularity=2,
        name="legacy#0",
    )
    stale_member = Edge(
        graph_variant_id=gv,
        type=EdgeType.MEMBER_OF,
        source_node_id=a.id,
        target_node_id=stale_community.id,
    )
    state = GraphBuildState(
        nodes=[a, b, stale_community],
        edges=[_entity_relation(a.id, b.id, gv), stale_member],
    )

    out = await LeidenClusterer().cluster(state, {"seed": 1})

    surviving_ids = {n.id for n in out.nodes}
    assert stale_community.id not in surviving_ids  # old community dropped

    surviving_member_edges = [e for e in out.edges if e.type == EdgeType.MEMBER_OF]
    surviving_member_targets = {e.target_node_id for e in surviving_member_edges}
    assert stale_community.id not in surviving_member_targets


async def test_leiden_empty_entity_layer_passes_through() -> None:
    state = GraphBuildState(nodes=[], edges=[])
    out = await LeidenClusterer().cluster(state, {})
    assert out.nodes == []
    assert out.edges == []


async def test_leiden_isolated_nodes_get_their_own_community() -> None:
    gv = new_id()
    a, b = _entity("A", gv), _entity("B", gv)
    state = GraphBuildState(nodes=[a, b], edges=[])

    out = await LeidenClusterer().cluster(state, {"seed": 0})

    community_nodes = [n for n in out.nodes if n.layer == Layer.COMMUNITY]
    assert len(community_nodes) == 2  # singleton communities


def test_leiden_descriptor_metadata() -> None:
    d = LeidenClusterer.descriptor
    assert d.kind == "clusterer"
    assert d.name == "leiden"
    assert Layer.ENTITY in d.requires_layers
    assert Layer.COMMUNITY in d.produces_layers


def test_bayan_descriptor_metadata_without_running() -> None:
    """bayanpy depends on Gurobi (heavy + license-walled). The clusterer
    is registered and discoverable, but we don't exercise it in CI.
    Run manually when needed.
    """

    from api.strategies.clusterers import BayanClusterer

    d = BayanClusterer.descriptor
    assert d.kind == "clusterer"
    assert d.name == "bayan"
    assert d.cost_hint == "moderate"


@pytest.mark.parametrize("size", [2, 5, 10])
async def test_leiden_membership_covers_every_entity(size: int) -> None:
    gv = new_id()
    nodes = [_entity(f"n{i}", gv) for i in range(size)]
    edges = [_entity_relation(nodes[i].id, nodes[(i + 1) % size].id, gv) for i in range(size)]
    state = GraphBuildState(nodes=nodes, edges=edges)

    out = await LeidenClusterer().cluster(state, {"seed": 0})

    member_edges = [e for e in out.edges if e.type == EdgeType.MEMBER_OF]
    sources = {e.source_node_id for e in member_edges}
    assert sources == {n.id for n in nodes}
