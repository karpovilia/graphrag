from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.strategies.builders  # noqa: F401
import api.strategies.cleaners  # noqa: F401
import api.strategies.clusterers  # noqa: F401
import api.tools  # noqa: F401
from api.eda.ner import EntityMention, NerProtocol
from api.repository import InMemoryRepository, RepositoryProtocol
from api.routes import corpora_router, graphs_router, tools_router
from api.routes.graphs import _maybe_llm
from api.runtime import get_ner, get_repository


class _FakeNer(NerProtocol):
    def __init__(self, mentions: dict[str, list[EntityMention]]) -> None:
        self._mentions = mentions

    def extract(self, text: str) -> list[EntityMention]:
        return list(self._mentions.get(text, ()))


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(corpora_router)
    app.include_router(graphs_router)
    app.include_router(tools_router)
    return app


@pytest.fixture
def repo() -> RepositoryProtocol:
    return InMemoryRepository()


@pytest.fixture
def fake_ner() -> _FakeNer:
    text = "Иванов работает в ВШЭ."
    return _FakeNer(
        {
            text: [
                EntityMention(text="Иванов", lemma="иванов", type="PER", start=0, end=6),
                EntityMention(text="ВШЭ", lemma="вшэ", type="ORG", start=18, end=21),
            ]
        }
    )


@pytest.fixture
def client(app: FastAPI, repo: RepositoryProtocol, fake_ner: _FakeNer) -> TestClient:
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_ner] = lambda: fake_ner
    app.dependency_overrides[_maybe_llm] = lambda: None
    return TestClient(app)


def _seed(client: TestClient) -> tuple[str, str, dict]:
    """Build a corpus + variant. Return (corpus_id, variant_id, nodes_by_name)."""

    corpus = client.post("/api/corpora", json={"name": "tools-fixture"}).json()
    cid = corpus["id"]
    client.post(
        f"/api/corpora/{cid}/documents",
        json={"title": "doc-1", "text": "Иванов работает в ВШЭ."},
    )
    variant = client.post(
        f"/api/corpora/{cid}/graphs",
        json={"name": "v", "builder": "ner_extraction"},
    ).json()
    vid = variant["id"]
    state = client.get(f"/api/graphs/{vid}/state").json()  # noqa: F841 — sanity
    # Pull full nodes via internal repo (no public route returns nodes yet).
    repo = client.app.dependency_overrides[get_repository]()
    import asyncio
    from uuid import UUID

    nodes_state = asyncio.run(repo.load_state(UUID(vid)))
    by_name = {n.name: n for n in nodes_state.nodes}
    return cid, vid, by_name


# ---- list_applicable_tools ----


def test_list_tools_for_person_includes_type_bound(client: TestClient) -> None:
    _, vid, by_name = _seed(client)
    person = by_name["Иванов"]
    resp = client.get(f"/api/nodes/{vid}/{person.id}/tools")
    assert resp.status_code == 200
    names = {t["name"] for t in resp.json()}
    # Universal tools always appear; type-bound tools appear because PERSON matches.
    assert {"show_neighbors", "show_evidence_chunks", "summarize_subgraph"}.issubset(names)
    assert "wikidata_lookup" in names
    assert "corpus_collocations" in names


def test_list_tools_for_chunk_excludes_person_only(client: TestClient) -> None:
    _, vid, by_name = _seed(client)
    chunk = next(n for n in by_name.values() if n.type == "CHUNK")
    resp = client.get(f"/api/nodes/{vid}/{chunk.id}/tools")
    assert resp.status_code == 200
    names = {t["name"] for t in resp.json()}
    # Type-bound tools (PERSON/ORG/PLACE) are filtered out for CHUNK.
    assert "wikidata_lookup" not in names
    assert "corpus_collocations" not in names
    # Universals remain.
    assert "summarize_subgraph" in names


# ---- run + history ----


def test_run_show_neighbors_persists_invocation(client: TestClient) -> None:
    _, vid, by_name = _seed(client)
    person = by_name["Иванов"]
    resp = client.post(
        f"/api/nodes/{vid}/{person.id}/tools/show_neighbors/run",
        json={"params": {}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tool"] == "show_neighbors"
    assert "neighbors_by_edge_type" in body["result"]

    history = client.get(f"/api/nodes/{vid}/{person.id}/tool_invocations").json()
    assert len(history) == 1
    assert history[0]["tool"] == "show_neighbors"


def test_run_type_bound_on_wrong_type_returns_400(client: TestClient) -> None:
    _, vid, by_name = _seed(client)
    chunk = next(n for n in by_name.values() if n.type == "CHUNK")
    resp = client.post(
        f"/api/nodes/{vid}/{chunk.id}/tools/wikidata_lookup/run",
        json={"params": {}},
    )
    assert resp.status_code == 400
    assert "does not apply" in resp.json()["detail"]


def test_run_unknown_tool_returns_404(client: TestClient) -> None:
    _, vid, by_name = _seed(client)
    person = by_name["Иванов"]
    resp = client.post(
        f"/api/nodes/{vid}/{person.id}/tools/no_such_tool/run", json={}
    )
    assert resp.status_code == 404


def test_run_unknown_node_returns_404(client: TestClient) -> None:
    _, vid, _ = _seed(client)
    bogus_id = "00000000-0000-0000-0000-000000000000"
    resp = client.post(
        f"/api/nodes/{vid}/{bogus_id}/tools/show_neighbors/run", json={}
    )
    assert resp.status_code == 404
