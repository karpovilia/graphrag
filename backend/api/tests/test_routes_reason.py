from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.agents  # noqa: F401
import api.strategies.aggregators  # noqa: F401
import api.strategies.builders  # noqa: F401
import api.strategies.cleaners  # noqa: F401
import api.strategies.clusterers  # noqa: F401
import api.strategies.reasoners  # noqa: F401
from api.eda.ner import EntityMention, NerProtocol
from api.repository import InMemoryRepository, RepositoryProtocol
from api.routes import reason_router
from api.routes import strategies_router  # noqa: F401  — populates the registries
from api.routes.eda import router as eda_router
from api.routes.graphs import _maybe_llm
from api.routes.graphs import router as graphs_router
from api.routes.corpora import router as corpora_router
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
    app.include_router(eda_router)
    app.include_router(graphs_router)
    app.include_router(reason_router)
    return app


@pytest.fixture
def repo() -> RepositoryProtocol:
    return InMemoryRepository()


@pytest.fixture
def fake_ner() -> _FakeNer:
    text = "Иванов И. работает с Петровым в ВШЭ."
    return _FakeNer(
        {
            text: [
                EntityMention(text="Иванов", lemma="иванов", type="PER", start=0, end=6),
                EntityMention(text="Петровым", lemma="петров", type="PER", start=20, end=28),
                EntityMention(text="ВШЭ", lemma="вшэ", type="ORG", start=32, end=35),
            ]
        }
    )


@pytest.fixture
def client(app: FastAPI, repo: RepositoryProtocol, fake_ner: _FakeNer) -> TestClient:
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_ner] = lambda: fake_ner
    app.dependency_overrides[_maybe_llm] = lambda: None
    return TestClient(app)


def _seed_two_variants(client: TestClient) -> tuple[str, str, str]:
    """Build a corpus with one document and two GraphVariants over the
    same documents — enough to exercise MoE.
    """

    corpus = client.post("/api/corpora", json={"name": "moe-fixture"}).json()
    corpus_id = corpus["id"]

    text = "Иванов И. работает с Петровым в ВШЭ."
    client.post(
        f"/api/corpora/{corpus_id}/documents",
        json={"title": "doc-1", "text": text},
    )

    v1 = client.post(
        f"/api/corpora/{corpus_id}/graphs",
        json={"name": "v1", "builder": "ner_extraction"},
    ).json()
    v2 = client.post(
        f"/api/corpora/{corpus_id}/graphs",
        json={
            "name": "v2",
            "builder": "ner_extraction",
            "builder_params": {"chunk_size": 20},
        },
    ).json()
    return corpus_id, v1["id"], v2["id"]


# ---- single mode ----


def test_reason_single_mode_returns_one_expert(client: TestClient) -> None:
    _, v1, _ = _seed_two_variants(client)

    resp = client.post(
        "/api/reason",
        json={
            "mode": "single",
            "query": "Иванов",
            "variant_ids": [v1],
            "reasoner": "keyword_search",
            "aggregator": "evidence_union",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["experts"]) == 1
    assert "Иванов" in body["answer"]["text"]


def test_reason_single_mode_rejects_multiple_variants(client: TestClient) -> None:
    _, v1, v2 = _seed_two_variants(client)
    resp = client.post(
        "/api/reason",
        json={
            "mode": "single",
            "query": "Иванов",
            "variant_ids": [v1, v2],
            "reasoner": "keyword_search",
        },
    )
    assert resp.status_code == 400
    assert "exactly one" in resp.json()["detail"]


# ---- moe mode ----


def test_reason_moe_mode_runs_all_variants(client: TestClient) -> None:
    _, v1, v2 = _seed_two_variants(client)
    resp = client.post(
        "/api/reason",
        json={
            "mode": "moe",
            "query": "Иванов",
            "variant_ids": [v1, v2],
            "reasoner": "keyword_search",
            "aggregator": "evidence_union",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["experts"]) == 2
    assert body["aggregator"] == "evidence_union"


def test_reason_moe_mode_rejects_single_variant(client: TestClient) -> None:
    _, v1, _ = _seed_two_variants(client)
    resp = client.post(
        "/api/reason",
        json={
            "mode": "moe",
            "query": "Иванов",
            "variant_ids": [v1],
            "reasoner": "keyword_search",
            "aggregator": "evidence_union",
        },
    )
    assert resp.status_code == 400
    assert "at least two" in resp.json()["detail"]


def test_reason_moe_with_weighted_vote(client: TestClient) -> None:
    _, v1, v2 = _seed_two_variants(client)
    resp = client.post(
        "/api/reason",
        json={
            "mode": "moe",
            "query": "Иванов",
            "variant_ids": [v1, v2],
            "reasoner": "keyword_search",
            "aggregator": "weighted_vote",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"]["metadata"]["aggregator"] == "weighted_vote"
    assert "winning_variant_id" in body["answer"]["metadata"]


def test_reason_unknown_reasoner_returns_400(client: TestClient) -> None:
    _, v1, v2 = _seed_two_variants(client)
    resp = client.post(
        "/api/reason",
        json={
            "mode": "moe",
            "query": "x",
            "variant_ids": [v1, v2],
            "reasoner": "no_such_reasoner",
            "aggregator": "evidence_union",
        },
    )
    assert resp.status_code == 400


# ---- SSE stream ----


def test_reason_stream_emits_expert_then_answer(client: TestClient) -> None:
    _, v1, v2 = _seed_two_variants(client)
    with client.stream(
        "POST",
        "/api/reason/stream",
        json={
            "mode": "moe",
            "query": "Иванов",
            "variant_ids": [v1, v2],
            "reasoner": "keyword_search",
            "aggregator": "evidence_union",
        },
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = "".join(chunk for chunk in resp.iter_text())

    # SSE frames: event lines + data lines, separated by blank lines.
    assert body.count("event: expert") == 2
    assert body.count("event: answer") == 1
    assert body.endswith("event: done\ndata: {}\n\n")
