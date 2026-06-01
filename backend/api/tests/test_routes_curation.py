"""End-to-end integration tests for the persisted graph + curation
routes. Use a fresh InMemoryRepository per test (and a fake NER) so the
suite stays fast and offline.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.eda.ner import EntityMention, NerProtocol
from api.repository import InMemoryRepository
from api.routes import corpora_router, eda_router, graphs_router, strategies_router
from api.routes.graphs import _maybe_llm
from api.runtime import get_ner, get_repository


class _FakeNer(NerProtocol):
    def __init__(self, by_text: dict[str, list[EntityMention]]) -> None:
        self._by_text = by_text

    def extract(self, text: str) -> list[EntityMention]:
        return list(self._by_text.get(text, ()))


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture
def ner_mentions() -> dict[str, list[EntityMention]]:
    return {
        "Иванов работает в ВШЭ. Иванов знаком с Петровым.": [
            EntityMention(text="Иванов", lemma="иванов", type="PER", start=0, end=6),
            EntityMention(text="ВШЭ", lemma="вшэ", type="ORG", start=18, end=21),
            EntityMention(text="Иванов", lemma="иванов", type="PER", start=23, end=29),
            EntityMention(text="Петровым", lemma="петров", type="PER", start=39, end=47),
        ],
    }


@pytest.fixture
def app(repo: InMemoryRepository, ner_mentions) -> FastAPI:
    a = FastAPI()
    a.include_router(strategies_router)
    a.include_router(corpora_router)
    a.include_router(eda_router)
    a.include_router(graphs_router)
    a.dependency_overrides[get_repository] = lambda: repo
    a.dependency_overrides[get_ner] = lambda: _FakeNer(ner_mentions)
    a.dependency_overrides[_maybe_llm] = lambda: None
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ---- corpus + document CRUD ----


def test_create_and_list_corpus(client: TestClient) -> None:
    resp = client.post("/api/corpora", json={"name": "HSE podcast"})
    assert resp.status_code == 201, resp.text
    corpus = resp.json()
    assert corpus["name"] == "HSE podcast"
    assert corpus["language"] == "ru"

    listed = client.get("/api/corpora").json()
    assert any(c["id"] == corpus["id"] for c in listed)


def test_create_document_increments_count(client: TestClient) -> None:
    corpus = client.post("/api/corpora", json={"name": "c"}).json()
    cid = corpus["id"]

    doc = client.post(
        f"/api/corpora/{cid}/documents",
        json={
            "title": "ep1",
            "text": "Иванов работает в ВШЭ. Иванов знаком с Петровым.",
        },
    )
    assert doc.status_code == 201, doc.text

    refreshed = client.get(f"/api/corpora/{cid}").json()
    assert refreshed["document_count"] == 1


def test_create_document_unknown_corpus_returns_404(client: TestClient) -> None:
    from uuid import uuid4

    resp = client.post(
        f"/api/corpora/{uuid4()}/documents",
        json={"title": "x", "text": "y"},
    )
    assert resp.status_code == 404


def test_get_document_returns_text_and_enforces_corpus(
    client: TestClient,
) -> None:
    from uuid import uuid4

    corpus = client.post("/api/corpora", json={"name": "c1"}).json()
    cid = corpus["id"]
    body = "Иванов работает в ВШЭ."
    doc = client.post(
        f"/api/corpora/{cid}/documents",
        json={"title": "ep1", "text": body},
    ).json()

    fetched = client.get(f"/api/corpora/{cid}/documents/{doc['id']}")
    assert fetched.status_code == 200, fetched.text
    payload = fetched.json()
    assert payload["id"] == doc["id"]
    assert payload["text"] == body
    assert payload["sha256"] == doc["sha256"]

    # Unknown id → 404
    missing = client.get(f"/api/corpora/{cid}/documents/{uuid4()}")
    assert missing.status_code == 404

    # Document exists but belongs to another corpus → 404
    other = client.post("/api/corpora", json={"name": "c2"}).json()
    cross = client.get(f"/api/corpora/{other['id']}/documents/{doc['id']}")
    assert cross.status_code == 404


# ---- variant build + persist ----


def _seed_corpus_with_doc(client: TestClient) -> tuple[str, str]:
    corpus = client.post("/api/corpora", json={"name": "c"}).json()
    cid = corpus["id"]
    doc = client.post(
        f"/api/corpora/{cid}/documents",
        json={
            "title": "ep1",
            "text": "Иванов работает в ВШЭ. Иванов знаком с Петровым.",
        },
    ).json()
    return cid, doc["id"]


def test_build_variant_persists_and_lists(client: TestClient) -> None:
    cid, _ = _seed_corpus_with_doc(client)

    resp = client.post(
        f"/api/corpora/{cid}/graphs",
        json={
            "name": "ner-baseline",
            "builder": "ner_extraction",
            "cleaner_chain": ["threshold_prune"],
            "clusterer": "leiden",
        },
    )
    assert resp.status_code == 201, resp.text
    variant = resp.json()
    assert variant["builder"] == "ner_extraction"
    assert variant["version"] == 0
    assert variant["node_count"] > 0

    listed = client.get(f"/api/graphs?corpus_id={cid}").json()
    assert any(v["id"] == variant["id"] for v in listed)


def test_build_variant_accepts_llm_override(client: TestClient) -> None:
    # Validates the wizard's bring-your-own-token shape: any
    # OpenAI-compatible base_url + model + (optional) api_key. We don't
    # actually call out to it — the `ner_extraction` builder used by the
    # fixture doesn't invoke an LLM, so the field just has to round-trip
    # through validation cleanly.
    cid, _ = _seed_corpus_with_doc(client)

    resp = client.post(
        f"/api/corpora/{cid}/graphs",
        json={
            "name": "byo-token",
            "builder": "ner_extraction",
            "llm_override": {
                "api_key": "sk-doesnt-matter-for-ner",
                "base_url": "http://localhost:11434/v1",
                "model": "qwen2.5:7b",
            },
        },
    )
    assert resp.status_code == 201, resp.text

    # Empty api_key is allowed (local servers don't authenticate).
    resp2 = client.post(
        f"/api/corpora/{cid}/graphs",
        json={
            "name": "byo-local",
            "builder": "ner_extraction",
            "llm_override": {
                "base_url": "http://localhost:8080/v1",
                "model": "llama-3.1-8b-instruct",
            },
        },
    )
    assert resp2.status_code == 201, resp2.text


def test_build_variant_rejects_empty_base_url(client: TestClient) -> None:
    cid, _ = _seed_corpus_with_doc(client)
    resp = client.post(
        f"/api/corpora/{cid}/graphs",
        json={
            "name": "bad",
            "builder": "ner_extraction",
            "llm_override": {"api_key": "x", "base_url": "", "model": "y"},
        },
    )
    assert resp.status_code == 422, resp.text


def test_build_variant_unknown_builder_returns_400(client: TestClient) -> None:
    cid, _ = _seed_corpus_with_doc(client)
    resp = client.post(
        f"/api/corpora/{cid}/graphs",
        json={"name": "x", "builder": "does_not_exist"},
    )
    assert resp.status_code == 400


def test_build_variant_empty_corpus_returns_400(client: TestClient) -> None:
    corpus = client.post("/api/corpora", json={"name": "empty"}).json()
    resp = client.post(
        f"/api/corpora/{corpus['id']}/graphs",
        json={"name": "x", "builder": "ner_extraction"},
    )
    assert resp.status_code == 400


def test_get_variant_state_summary(client: TestClient) -> None:
    cid, _ = _seed_corpus_with_doc(client)
    variant = client.post(
        f"/api/corpora/{cid}/graphs",
        json={"name": "v", "builder": "ner_extraction"},
    ).json()

    resp = client.get(f"/api/graphs/{variant['id']}/state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == 0
    assert body["node_count"] == variant["node_count"]
    assert "entity" in body["nodes_by_layer"]


# ---- journal append + optimistic locking ----


def test_journal_append_changes_version_and_state(client: TestClient) -> None:
    cid, _ = _seed_corpus_with_doc(client)
    variant = client.post(
        f"/api/corpora/{cid}/graphs",
        json={"name": "v", "builder": "ner_extraction"},
    ).json()

    state = client.get(f"/api/graphs/{variant['id']}/state").json()
    target_id = _first_entity_id(client, variant["id"])

    resp = client.post(
        f"/api/graphs/{variant['id']}/journal",
        json={
            "op": "update_node_name",
            "payload": {"node_id": target_id, "name": "Renamed"},
            "expected_version": state["version"],
            "actor": "user:test",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["variant"]["version"] == state["version"] + 1
    assert body["entry"]["op"] == "update_node_name"
    # §2.3 latency badge: recompute_ms always present and >= 0.0.
    assert "recompute_ms" in body
    assert body["recompute_ms"] >= 0.0

    journal = client.get(f"/api/graphs/{variant['id']}/journal").json()
    assert len(journal) == 1


def test_concurrent_edit_returns_409(client: TestClient) -> None:
    cid, _ = _seed_corpus_with_doc(client)
    variant = client.post(
        f"/api/corpora/{cid}/graphs",
        json={"name": "v", "builder": "ner_extraction"},
    ).json()
    target_id = _first_entity_id(client, variant["id"])

    base_payload = {
        "op": "update_node_name",
        "payload": {"node_id": target_id, "name": "First"},
        "expected_version": 0,
        "actor": "user:a",
    }
    assert client.post(
        f"/api/graphs/{variant['id']}/journal", json=base_payload
    ).status_code == 200

    stale_payload = {
        **base_payload,
        "payload": {"node_id": target_id, "name": "Second"},
        "actor": "user:b",
    }
    resp = client.post(
        f"/api/graphs/{variant['id']}/journal", json=stale_payload
    )
    assert resp.status_code == 409
    body = resp.json()["detail"]
    assert body["expected"] == 0
    assert body["actual"] == 1


def test_invalid_payload_returns_422(client: TestClient) -> None:
    cid, _ = _seed_corpus_with_doc(client)
    variant = client.post(
        f"/api/corpora/{cid}/graphs",
        json={"name": "v", "builder": "ner_extraction"},
    ).json()

    resp = client.post(
        f"/api/graphs/{variant['id']}/journal",
        json={
            "op": "merge_nodes",
            "payload": {"absorbed_ids": []},  # missing survivor_id
            "expected_version": 0,
            "actor": "user:test",
        },
    )
    assert resp.status_code == 422


# ---- undo ----


def test_undo_reverts_state_and_pops_journal(client: TestClient) -> None:
    cid, _ = _seed_corpus_with_doc(client)
    variant = client.post(
        f"/api/corpora/{cid}/graphs",
        json={"name": "v", "builder": "ner_extraction"},
    ).json()
    target_id = _first_entity_id(client, variant["id"])

    client.post(
        f"/api/graphs/{variant['id']}/journal",
        json={
            "op": "update_node_name",
            "payload": {"node_id": target_id, "name": "X"},
            "expected_version": 0,
            "actor": "user:test",
        },
    )

    state = client.get(f"/api/graphs/{variant['id']}/state").json()
    resp = client.post(
        f"/api/graphs/{variant['id']}/undo",
        json={"expected_version": state["version"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["entry"]["op"] == "update_node_name"
    assert body["variant"]["version"] == state["version"] + 1
    assert "recompute_ms" in body
    assert body["recompute_ms"] >= 0.0

    journal_after = client.get(f"/api/graphs/{variant['id']}/journal").json()
    assert journal_after == []


def test_undo_empty_journal_returns_400(client: TestClient) -> None:
    cid, _ = _seed_corpus_with_doc(client)
    variant = client.post(
        f"/api/corpora/{cid}/graphs",
        json={"name": "v", "builder": "ner_extraction"},
    ).json()

    resp = client.post(
        f"/api/graphs/{variant['id']}/undo",
        json={"expected_version": 0},
    )
    assert resp.status_code == 400


# ---- layout cache ----


def test_layout_round_trip_and_global_fallback(client: TestClient) -> None:
    cid, _ = _seed_corpus_with_doc(client)
    variant = client.post(
        f"/api/corpora/{cid}/graphs",
        json={"name": "v", "builder": "ner_extraction"},
    ).json()
    vid = variant["id"]

    # No layout yet → empty positions, marked as "global".
    empty = client.get(f"/api/graphs/{vid}/layout")
    assert empty.status_code == 200, empty.text
    assert empty.json() == {"positions": {}, "owner": "global"}

    # Anonymous PUT — feeds the shared pool.
    payload = {"positions": {"node-a": [1.0, 2.0], "node-b": [3.5, -7.25]}}
    put = client.put(f"/api/graphs/{vid}/layout", json=payload)
    assert put.status_code == 200, put.text
    assert put.json()["positions"]["node-a"] == [1.0, 2.0]

    # Subsequent anonymous GET reads back the same positions.
    refetch = client.get(f"/api/graphs/{vid}/layout").json()
    assert refetch["positions"]["node-b"] == [3.5, -7.25]
    assert refetch["owner"] == "global"


def test_layout_unknown_variant_returns_404(client: TestClient) -> None:
    from uuid import uuid4

    missing = uuid4()
    resp_get = client.get(f"/api/graphs/{missing}/layout")
    assert resp_get.status_code == 404
    resp_put = client.put(
        f"/api/graphs/{missing}/layout",
        json={"positions": {}},
    )
    assert resp_put.status_code == 404


# ---- helpers ----


def _first_entity_id(client: TestClient, variant_id: str) -> str:
    """Lift a real entity-layer node id from the persisted state.

    /api/graphs/{id}/state returns counts by layer, not the actual node
    ids. For this test fixture (which uses _FakeNer) we reach into the
    repository via the dependency override the route already wires.
    """

    import asyncio
    from uuid import UUID

    from api.domain.graph import Layer

    repo = client.app.dependency_overrides[get_repository]()
    state = asyncio.run(repo.load_state(UUID(variant_id)))

    for n in state.nodes:
        if n.layer == Layer.ENTITY:
            return str(n.id)
    raise AssertionError("no entity-layer node in seeded variant")
