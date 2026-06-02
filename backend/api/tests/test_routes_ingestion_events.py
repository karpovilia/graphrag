"""Tests for POST /api/corpora/{cid}/ingestion-events (R2 §2 timeline seed).

The endpoint records a timeline unit *and* staggered-backfills the linked
variant's bi-temporal stamps (tx_from / valid_from) on previously-null
nodes/edges, so materialize_at / diff on the tx axis compresses the graph
over time. This is the only backend route the e2e seed (e2e/lib/seed.ts)
depends on to leave the temporal specs un-skipped.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.domain.corpus import Corpus
from api.domain.graph import (
    Edge,
    EdgeType,
    GraphVariant,
    GraphVariantStatus,
    Layer,
    Node,
)
from api.domain.types import new_id
from api.repository import InMemoryRepository
from api.routes import corpora_router, graphs_router, temporal_router
from api.runtime import get_repository
from api.strategies.state import GraphBuildState


def _run(coro):
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
    corpus = Corpus(name="c")
    cid = corpus.id
    vid = new_id()
    # Two nodes + one edge, all with null tx_from (legacy / fresh build).
    n1 = Node(graph_variant_id=vid, layer=Layer.ENTITY, type="PERSON", granularity=1, name="A")
    n2 = Node(graph_variant_id=vid, layer=Layer.ENTITY, type="PERSON", granularity=1, name="B")
    e = Edge(
        graph_variant_id=vid, type=EdgeType.ENTITY_RELATION,
        source_node_id=n1.id, target_node_id=n2.id,
    )
    state = GraphBuildState(nodes=[n1, n2], edges=[e])
    variant = GraphVariant(
        id=vid, corpus_id=cid, name="v", status=GraphVariantStatus.READY, builder="lightrag",
    )

    async def _setup():
        await repo.create_corpus(corpus)
        await repo.create_variant(variant, state)

    _run(_setup())
    return {"cid": cid, "vid": vid, "n1": n1, "n2": n2, "e": e}


@pytest.fixture
def client(repo: InMemoryRepository) -> TestClient:
    a = FastAPI()
    a.include_router(corpora_router)
    a.dependency_overrides[get_repository] = lambda: repo
    return TestClient(a)


def _ev_body(vid, label, event_time, ingested_at):
    return {
        "label": label,
        "event_time": event_time,
        "ingested_at": ingested_at,
        "graph_variant_id": str(vid),
        "kind": "episode",
    }


def test_create_event_returns_201_and_id(client, seeded):
    resp = client.post(
        f"/api/corpora/{seeded['cid']}/ingestion-events",
        json=_ev_body(
            seeded["vid"], "Эпизод 1", "2024-01-10T00:00:00Z", "2024-01-12T00:00:00Z"
        ),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"]
    assert body["label"] == "Эпизод 1"
    assert body["graph_variant_id"] == str(seeded["vid"])


def test_backfill_stamps_tx_from(client, seeded, repo):
    client.post(
        f"/api/corpora/{seeded['cid']}/ingestion-events",
        json=_ev_body(
            seeded["vid"], "Эпизод 1", "2024-01-10T00:00:00Z", "2024-01-12T00:00:00Z"
        ),
    )
    state = _run(repo.load_state(seeded["vid"]))
    # Every previously-null node/edge now has tx_from + valid_from filled.
    for n in state.nodes:
        assert n.tx_from is not None
        assert n.valid_from is not None
    for e in state.edges:
        assert e.tx_from is not None
    # Single bucket → first ingested_at.
    assert state.nodes[0].tx_from == datetime(2024, 1, 12, tzinfo=timezone.utc)


def test_backfill_is_idempotent_and_staggered(client, seeded, repo):
    # Two episodes: bucket 0 = ep1 ingested_at, bucket 1 = ep2 ingested_at.
    client.post(
        f"/api/corpora/{seeded['cid']}/ingestion-events",
        json=_ev_body(seeded["vid"], "ep1", "2024-01-10T00:00:00Z", "2024-01-12T00:00:00Z"),
    )
    client.post(
        f"/api/corpora/{seeded['cid']}/ingestion-events",
        json=_ev_body(seeded["vid"], "ep2", "2024-02-10T00:00:00Z", "2024-02-12T00:00:00Z"),
    )
    state = _run(repo.load_state(seeded["vid"]))
    # First node already stamped at bucket 0 by the first POST stays there
    # (idempotent: only NULLs get filled).
    assert state.nodes[0].tx_from == datetime(2024, 1, 12, tzinfo=timezone.utc)


def test_unknown_corpus_404(client, seeded):
    resp = client.post(
        f"/api/corpora/{new_id()}/ingestion-events",
        json=_ev_body(seeded["vid"], "x", "2024-01-10T00:00:00Z", "2024-01-12T00:00:00Z"),
    )
    assert resp.status_code == 404


def test_unknown_variant_404(client, seeded):
    resp = client.post(
        f"/api/corpora/{seeded['cid']}/ingestion-events",
        json=_ev_body(new_id(), "x", "2024-01-10T00:00:00Z", "2024-01-12T00:00:00Z"),
    )
    assert resp.status_code == 404


@pytest.fixture
def full_client(repo: InMemoryRepository) -> TestClient:
    a = FastAPI()
    a.include_router(corpora_router)
    a.include_router(graphs_router)
    a.include_router(temporal_router)
    a.dependency_overrides[get_repository] = lambda: repo
    return TestClient(a)


def test_seed_flow_soft_delete_shows_in_diff(full_client, seeded, repo):
    """Mirror e2e/lib/seed.ts: post the 4-episode time series (Эп.3
    back-dated, ingested last), then DELETE_EDGE-with-reason linked to
    Эп.3 via the journal route. The edge must land in diff(tx_a, tx_b,
    axis=tx).invalidated and be revert-eligible."""
    cid, vid = seeded["cid"], seeded["vid"]
    episodes = [
        ("Эпизод 1", "2024-01-10T00:00:00Z", "2024-01-12T00:00:00Z"),
        ("Эпизод 2", "2024-02-10T00:00:00Z", "2024-02-12T00:00:00Z"),
        ("Эпизод 3", "2024-03-10T00:00:00Z", "2024-05-20T00:00:00Z"),  # back-dated
        ("Эпизод 4", "2024-04-10T00:00:00Z", "2024-04-12T00:00:00Z"),
    ]
    ep_ids: dict[str, str] = {}
    for label, et, it in episodes:
        r = full_client.post(
            f"/api/corpora/{cid}/ingestion-events", json=_ev_body(vid, label, et, it)
        )
        assert r.status_code == 201, r.text
        ep_ids[label] = r.json()["id"]

    # tx_a = just after Эп.1 ingest; tx_b = just after the last (Эп.3) ingest.
    tx_a = "2024-01-12T00:00:01Z"
    tx_b = "2024-05-20T00:00:01Z"

    edge_id = str(seeded["e"].id)
    variant = _run(repo.get_variant(vid))
    r = full_client.post(
        f"/api/graphs/{vid}/journal",
        json={
            "op": "delete_edge",
            "payload": {
                "edge_id": edge_id,
                "reason": "superseded by Эпизод 3 re-extraction",
                "ingestion_event_id": ep_ids["Эпизод 3"],
            },
            "expected_version": variant.version,
            "actor": "agent:ingestion",
        },
    )
    assert r.status_code == 200, r.text
    new_version = r.json()["variant"]["version"]

    # The edge survives (soft delete) with tx_to == Эп.3 ingested_at.
    state = _run(repo.load_state(vid))
    survived = next(e for e in state.edges if str(e.id) == edge_id)
    assert survived.tx_to == datetime(2024, 5, 20, tzinfo=timezone.utc)
    assert survived.invalidation is not None
    assert survived.invalidation.auto is True

    # diff(tx_a, tx_b, axis=tx).invalidated contains the edge.
    diff = full_client.get(
        f"/api/graphs/{vid}/diff", params={"t_a": tx_a, "t_b": tx_b, "axis": "tx"}
    ).json()
    inv_ids = {e["id"] for e in diff["invalidated"]}
    assert edge_id in inv_ids

    # Revert un-kills it (clears tx_to + invalidation).
    r = full_client.post(
        f"/api/graphs/{vid}/invalidations/{edge_id}/revert",
        json={"expected_version": new_version, "actor": "user:t@e.st"},
    )
    assert r.status_code == 200, r.text
    state = _run(repo.load_state(vid))
    reverted = next(e for e in state.edges if str(e.id) == edge_id)
    assert reverted.tx_to is None
    assert reverted.invalidation is None
