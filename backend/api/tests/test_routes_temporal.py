"""Integration tests for the bi-temporal routes (R2 §2).

Seed an InMemoryRepository directly (no build pipeline) so the suite
stays fast and deterministic.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.domain.corpus import Corpus
from api.domain.graph import (
    Edge,
    EdgeInvalidation,
    EdgeType,
    GraphVariant,
    GraphVariantStatus,
    Layer,
    Node,
)
from api.domain.temporal import IngestionEvent
from api.domain.types import new_id
from api.repository import InMemoryRepository
from api.routes import temporal_router
from api.runtime import get_repository
from api.strategies.state import GraphBuildState

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _t(days: int) -> datetime:
    return T0 + timedelta(days=days)


def _iso(days: int) -> str:
    return _t(days).isoformat().replace("+00:00", "Z")


def _run(coro):
    """Drive a coroutine to completion on a fresh loop — robust under the
    full suite where a prior test may have closed the thread's loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture
def seeded(repo: InMemoryRepository):
    """A corpus + variant with two nodes, an edge that dies plain and an
    edge that dies via invalidation, plus two ingestion events."""


    corpus = Corpus(name="c")
    cid = corpus.id
    vid = new_id()

    n1 = Node(
        id=new_id(), graph_variant_id=vid, layer=Layer.ENTITY, type="PERSON",
        granularity=1, name="A", tx_from=_t(0), tx_to=None,
    )
    n2 = Node(
        id=new_id(), graph_variant_id=vid, layer=Layer.ENTITY, type="PERSON",
        granularity=1, name="B", tx_from=_t(9), tx_to=None,  # born later
    )
    plain = Edge(
        id=new_id(), graph_variant_id=vid, type=EdgeType.ENTITY_RELATION,
        source_node_id=n1.id, target_node_id=n1.id, tx_from=_t(0), tx_to=_t(8),
    )
    inv = Edge(
        id=new_id(), graph_variant_id=vid, type=EdgeType.ENTITY_RELATION,
        source_node_id=n1.id, target_node_id=n1.id, tx_from=_t(0), tx_to=_t(8),
        invalidation=EdgeInvalidation(at=_t(8), reason="superseded", auto=True),
    )
    state = GraphBuildState(nodes=[n1, n2], edges=[plain, inv])
    variant = GraphVariant(
        id=vid, corpus_id=cid, name="v", status=GraphVariantStatus.READY,
        builder="lightrag",
    )

    ev1 = IngestionEvent(
        corpus_id=cid, graph_variant_id=vid, label="ep1",
        event_time=_t(0), ingested_at=_t(0),
    )
    ev2 = IngestionEvent(
        corpus_id=cid, graph_variant_id=vid, label="ep2",
        event_time=_t(20), ingested_at=_t(9),
    )

    async def _setup():
        await repo.create_corpus(corpus)
        await repo.create_variant(variant, state)
        await repo.create_ingestion_event(ev1)
        await repo.create_ingestion_event(ev2)

    _run(_setup())
    return {
        "cid": cid, "vid": vid, "n1": n1, "n2": n2,
        "plain": plain, "inv": inv, "ev1": ev1, "ev2": ev2,
    }


@pytest.fixture
def app(repo: InMemoryRepository) -> FastAPI:
    a = FastAPI()
    a.include_router(temporal_router)
    a.dependency_overrides[get_repository] = lambda: repo
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ---- /timeline ----


def test_timeline_orders_by_axis(client: TestClient, seeded) -> None:
    vid = seeded["vid"]
    # axis=tx → ascending by ingested_at: ev1 (day0) then ev2 (day9)
    tx = client.get(f"/api/graphs/{vid}/timeline", params={"axis": "tx"})
    assert tx.status_code == 200, tx.text
    labels_tx = [e["label"] for e in tx.json()]
    assert labels_tx == ["ep1", "ep2"]

    # axis=valid → ascending by event_time: ev1 (day0) then ev2 (day20)
    val = client.get(f"/api/graphs/{vid}/timeline", params={"axis": "valid"})
    assert [e["label"] for e in val.json()] == ["ep1", "ep2"]


def test_timeline_unknown_variant_404(client: TestClient) -> None:
    resp = client.get(f"/api/graphs/{new_id()}/timeline")
    assert resp.status_code == 404


def test_timeline_bad_axis_422(client: TestClient, seeded) -> None:
    resp = client.get(
        f"/api/graphs/{seeded['vid']}/timeline", params={"axis": "nope"}
    )
    assert resp.status_code == 422


# ---- /at ----


def test_at_returns_live_ids(client: TestClient, seeded) -> None:
    vid = seeded["vid"]
    # at day 5: n1 live, n2 not yet; both edges live
    resp = client.get(f"/api/graphs/{vid}/at", params={"t": _iso(5), "axis": "tx"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert str(seeded["n1"].id) in body["node_ids"]
    assert str(seeded["n2"].id) not in body["node_ids"]
    assert str(seeded["plain"].id) in body["edge_ids"]
    assert str(seeded["inv"].id) in body["edge_ids"]

    # at day 10: n2 born, both edges dead
    resp2 = client.get(f"/api/graphs/{vid}/at", params={"t": _iso(10), "axis": "tx"})
    body2 = resp2.json()
    assert str(seeded["n2"].id) in body2["node_ids"]
    assert str(seeded["plain"].id) not in body2["edge_ids"]


# ---- /diff ----


def test_diff_happy_path(client: TestClient, seeded) -> None:
    vid = seeded["vid"]
    resp = client.get(
        f"/api/graphs/{vid}/diff",
        params={"t_a": _iso(5), "t_b": _iso(10), "axis": "tx"},
    )
    assert resp.status_code == 200, resp.text
    diff = resp.json()
    born_ids = {e["id"] for e in diff["born"]}
    dead_ids = {e["id"] for e in diff["dead"]}
    inv_ids = {e["id"] for e in diff["invalidated"]}
    assert str(seeded["n2"].id) in born_ids
    assert str(seeded["plain"].id) in dead_ids
    assert str(seeded["inv"].id) in inv_ids
    assert dead_ids.isdisjoint(inv_ids)
    assert diff["counts"]["invalidated"] == 1


def test_diff_bad_axis_422(client: TestClient, seeded) -> None:
    resp = client.get(
        f"/api/graphs/{seeded['vid']}/diff",
        params={"t_a": _iso(5), "t_b": _iso(10), "axis": "bogus"},
    )
    assert resp.status_code == 422


def test_diff_ta_after_tb_400(client: TestClient, seeded) -> None:
    resp = client.get(
        f"/api/graphs/{seeded['vid']}/diff",
        params={"t_a": _iso(10), "t_b": _iso(5), "axis": "tx"},
    )
    assert resp.status_code == 400


def test_diff_unknown_variant_404(client: TestClient) -> None:
    resp = client.get(
        f"/api/graphs/{new_id()}/diff",
        params={"t_a": _iso(5), "t_b": _iso(10), "axis": "tx"},
    )
    assert resp.status_code == 404


# ---- /invalidations/{edge_id}/revert ----


def test_revert_clears_invalidation_and_bumps_version(
    client: TestClient, seeded, repo: InMemoryRepository
) -> None:

    vid = seeded["vid"]
    edge_id = seeded["inv"].id
    variant = _run(repo.get_variant(vid))

    resp = client.post(
        f"/api/graphs/{vid}/invalidations/{edge_id}/revert",
        json={"expected_version": variant.version, "actor": "user:t@e.st"},
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["variant"]["version"] == variant.version + 1
    assert "recompute_ms" in result and result["recompute_ms"] >= 0.0

    # invalidation cleared on the reloaded edge
    state = _run(repo.load_state(vid))
    edge = next(e for e in state.edges if e.id == edge_id)
    assert edge.invalidation is None
    assert edge.tx_to is None


def test_revert_stale_version_409(client: TestClient, seeded) -> None:
    vid = seeded["vid"]
    resp = client.post(
        f"/api/graphs/{vid}/invalidations/{seeded['inv'].id}/revert",
        json={"expected_version": 999, "actor": "user:t@e.st"},
    )
    assert resp.status_code == 409


def test_revert_non_invalidated_edge_400(
    client: TestClient, seeded, repo: InMemoryRepository
) -> None:

    vid = seeded["vid"]
    # plain edge has tx_to set but no invalidation — still treated as
    # invalidated-by-time? plain has tx_to=_t(8); contract says 400 when
    # not invalidated. We assert the *born* node-attached live edge case
    # by adding a clean live edge.
    state = _run(repo.load_state(vid))
    live_edge = Edge(
        id=new_id(), graph_variant_id=vid, type=EdgeType.ENTITY_RELATION,
        source_node_id=seeded["n1"].id, target_node_id=seeded["n1"].id,
        tx_from=_t(0), tx_to=None,
    )
    state.edges.append(live_edge)

    variant = _run(repo.get_variant(vid))
    resp = client.post(
        f"/api/graphs/{vid}/invalidations/{live_edge.id}/revert",
        json={"expected_version": variant.version, "actor": "user:t@e.st"},
    )
    assert resp.status_code == 400


def test_revert_unknown_edge_404(client: TestClient, seeded) -> None:
    vid = seeded["vid"]
    resp = client.post(
        f"/api/graphs/{vid}/invalidations/{new_id()}/revert",
        json={"expected_version": 0, "actor": "user:t@e.st"},
    )
    assert resp.status_code == 404
