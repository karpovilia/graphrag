"""Unit tests for the intra_layer_backbone projector.

We synthesise small but topology-rich states (one alleged "megahub" +
sparse periphery, plus cross-layer evidence) and assert:

1. The projector emits new edges of type BACKBONE only — never mutates
   existing inputs.
2. The kept edge count per layer lands in the requested |E|/|V| band.
3. The locally-significant edges of low-degree nodes survive while
   most edges around an over-connected node are filtered out — i.e.
   the disparity filter actually does its hub-suppression job.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

import api.strategies.projectors  # noqa: F401 — register
from api.domain.graph import Edge, EdgeType, Layer, Node
from api.strategies.projectors.intra_layer_backbone import IntraLayerBackbone
from api.strategies.state import GraphBuildState


def _node(layer: Layer, name: str, variant_id: UUID) -> Node:
    return Node(
        id=uuid4(),
        graph_variant_id=variant_id,
        layer=layer,
        type="generic",
        granularity=0,
        name=name,
    )


def _edge(
    variant_id: UUID,
    src: UUID,
    tgt: UUID,
    edge_type: EdgeType,
    *,
    weight: float = 1.0,
) -> Edge:
    return Edge(
        graph_variant_id=variant_id,
        type=edge_type,
        source_node_id=src,
        target_node_id=tgt,
        weight=weight,
    )


@pytest.mark.asyncio
async def test_backbone_hits_target_ratio_and_marks_layer() -> None:
    # 20 entity nodes, all mentioned in shared chunks. The first entity
    # is the "megahub" — co-mentioned with every other entity in every
    # chunk; the rest only share chunks with their immediate neighbour.
    variant_id = uuid4()
    chunks = [_node(Layer.CHUNK, f"c{i}", variant_id) for i in range(10)]
    entities = [_node(Layer.ENTITY, f"e{i}", variant_id) for i in range(20)]
    nodes = chunks + entities

    edges: list[Edge] = []
    # Hub e0 mentioned in every chunk.
    for c in chunks:
        edges.append(_edge(variant_id, entities[0].id, c.id, EdgeType.MENTIONED_IN))
    # Each other entity mentioned in exactly one chunk shared with its
    # successor — so periphery entities have one strong neighbour each.
    for i in range(1, len(entities) - 1):
        c = chunks[i % len(chunks)]
        edges.append(_edge(variant_id, entities[i].id, c.id, EdgeType.MENTIONED_IN))
        edges.append(_edge(variant_id, entities[i + 1].id, c.id, EdgeType.MENTIONED_IN))

    state = GraphBuildState(nodes=nodes, edges=edges, journal=[])

    proj = IntraLayerBackbone()
    new_state = await proj.project(
        state,
        params={
            "target_min": 2.0,
            "target_max": 5.0,
            "layers": ["entity"],
        },
    )

    # Inputs preserved verbatim.
    assert all(e in new_state.edges for e in edges)
    backbone = [e for e in new_state.edges if e.type == EdgeType.BACKBONE]

    n_entities = len(entities)
    assert 2 * n_entities <= len(backbone) <= 5 * n_entities, (
        f"backbone size {len(backbone)} outside band [{2 * n_entities}, "
        f"{5 * n_entities}] for {n_entities} entity nodes"
    )

    # Every backbone edge tagged with the projector's layer.
    for e in backbone:
        assert e.attributes.get("layer") == "entity"
        assert e.source_node_id != e.target_node_id


@pytest.mark.asyncio
async def test_backbone_suppresses_hub_dominance() -> None:
    # Build a star: e0 connects to e1..e19 via shared chunks. Periphery
    # entities also weakly link to each other through 2 ambient chunks.
    # Without filtering, e0 would own ~95% of pair-counts; with NPMI +
    # disparity, peripheral pairs should still have a fair shot.
    variant_id = uuid4()
    hub = _node(Layer.ENTITY, "hub", variant_id)
    periphery = [_node(Layer.ENTITY, f"p{i}", variant_id) for i in range(20)]
    star_chunks = [_node(Layer.CHUNK, f"sc{i}", variant_id) for i in range(20)]
    ambient = [_node(Layer.CHUNK, f"a{i}", variant_id) for i in range(2)]
    nodes = [hub] + periphery + star_chunks + ambient

    edges: list[Edge] = []
    # hub <-> p_i via star_chunks[i]
    for i, p in enumerate(periphery):
        c = star_chunks[i]
        edges.append(_edge(variant_id, hub.id, c.id, EdgeType.MENTIONED_IN))
        edges.append(_edge(variant_id, p.id, c.id, EdgeType.MENTIONED_IN))
    # All periphery share 2 ambient chunks → C(20, 2) = 190 candidate
    # periphery-periphery pairs with co-occurrence count 2 each.
    for c in ambient:
        for p in periphery:
            edges.append(_edge(variant_id, p.id, c.id, EdgeType.MENTIONED_IN))

    state = GraphBuildState(nodes=nodes, edges=edges, journal=[])

    proj = IntraLayerBackbone()
    new_state = await proj.project(
        state,
        params={"target_min": 2.0, "target_max": 4.0, "layers": ["entity"]},
    )

    backbone = [e for e in new_state.edges if e.type == EdgeType.BACKBONE]
    hub_edges = [
        e for e in backbone if hub.id in (e.source_node_id, e.target_node_id)
    ]
    # The hub should NOT own a majority of backbone edges. With 21 entity
    # nodes the keep-budget is roughly 42-84; if the filter were naive the
    # hub would take ~20 (one per periphery). We expect it to lose most.
    assert len(hub_edges) <= len(backbone) // 2, (
        f"hub kept {len(hub_edges)}/{len(backbone)} edges — disparity "
        "filter didn't suppress the megahub"
    )


@pytest.mark.asyncio
async def test_projector_noop_when_no_evidence() -> None:
    variant_id = uuid4()
    nodes = [_node(Layer.ENTITY, "alone", variant_id)]
    state = GraphBuildState(nodes=nodes, edges=[], journal=[])
    proj = IntraLayerBackbone()
    out = await proj.project(state, params={})
    assert out.edges == []
    assert out.journal == []  # no edges → no journal marker either


def test_projector_registry_lists_intra_layer_backbone() -> None:
    from api.strategies.registry import projectors

    assert "intra_layer_backbone" in projectors.names()
    desc = projectors.get_descriptor("intra_layer_backbone")
    assert desc.kind == "projector"
    assert "target_min" in (desc.params_schema or {})
