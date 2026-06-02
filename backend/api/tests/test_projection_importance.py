"""Tests for projection-importance analysis + its route."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.analysis import compute_projection_importance
from api.domain.corpus import Corpus
from api.domain.graph import (
    Edge,
    EdgeType,
    GraphVariant,
    GraphVariantStatus,
    Layer,
    Node,
)
from api.repository import InMemoryRepository
from api.routes.analysis import router as analysis_router
from api.runtime import get_repository
from api.strategies.state import GraphBuildState


def _ent(vid, name):
    return Node(id=uuid4(), graph_variant_id=vid, layer=Layer.ENTITY,
               type="PERSON", granularity=1, name=name)


def _derived(vid, a, b, proj, w=1.0):
    return Edge(id=uuid4(), graph_variant_id=vid, type=EdgeType.DERIVED,
                source_node_id=a, target_node_id=b, weight=w,
                relation=proj, attributes={"order": 2, "projection": proj})


def _state(vid):
    A, B, C, D, E = (_ent(vid, n) for n in "ABCDE")
    edges = [
        # P1: triangle A-B-C
        _derived(vid, A.id, B.id, "P1"), _derived(vid, A.id, C.id, "P1"),
        _derived(vid, B.id, C.id, "P1"),
        # P1dup: identical triangle → redundant with P1
        _derived(vid, A.id, B.id, "P1dup"), _derived(vid, A.id, C.id, "P1dup"),
        _derived(vid, B.id, C.id, "P1dup"),
        # P2: a distinct edge D-E
        _derived(vid, D.id, E.id, "P2"),
    ]
    return GraphBuildState(nodes=[A, B, C, D, E], edges=edges), (A, B, C, D, E)


def test_compute_ranks_and_finds_redundant_pair():
    vid = uuid4()
    state, _ = _state(vid)
    res = compute_projection_importance(state, vid)

    names = {p.name for p in res.projections}
    assert names == {"P1", "P1dup", "P2"}
    assert res.spectral_computed is True
    # identical projections are the lowest-JSD (most redundant) pair
    assert set(res.most_redundant_pair) == {"P1", "P1dup"}

    by = {p.name: p for p in res.projections}
    # P2's only pair is unique to it; P1/P1dup fully overlap each other
    assert by["P2"].unique_pair_fraction == 1.0
    assert by["P1"].unique_pair_fraction == 0.0
    assert by["P1dup"].unique_pair_fraction == 0.0
    # ranking is most-distinct-first
    assert res.projections[0].distinctiveness_jsd is not None


def test_compute_empty_when_no_derived():
    vid = uuid4()
    state = GraphBuildState(nodes=[_ent(vid, "A")], edges=[])
    res = compute_projection_importance(state, vid)
    assert res.projections == []
    assert res.spectral_computed is False
    assert "multiprojection" in (res.note or "")


@pytest.fixture
def repo():
    return InMemoryRepository()


@pytest.fixture
def client(repo):
    app = FastAPI()
    app.include_router(analysis_router)
    app.dependency_overrides[get_repository] = lambda: repo
    return TestClient(app)


def test_route_returns_importance(client, repo):
    vid = uuid4()
    state, _ = _state(vid)
    corpus = Corpus(name="c")
    variant = GraphVariant(id=vid, corpus_id=corpus.id, name="v",
                           status=GraphVariantStatus.READY, builder="lightrag")

    async def _setup():
        await repo.create_corpus(corpus)
        await repo.create_variant(variant, state)

    asyncio.run(_setup())

    r = client.get(f"/api/graphs/{vid}/projection-importance")
    assert r.status_code == 200
    body = r.json()
    assert {p["name"] for p in body["projections"]} == {"P1", "P1dup", "P2"}
    assert set(body["most_redundant_pair"]) == {"P1", "P1dup"}


def test_route_404_unknown_variant(client):
    r = client.get(f"/api/graphs/{uuid4()}/projection-importance")
    assert r.status_code == 404
