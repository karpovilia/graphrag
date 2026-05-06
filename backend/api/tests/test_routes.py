from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.eda.ner import EntityMention, NerProtocol
from api.llm import CompletionClient, CompletionParams, CompletionResult, Message
from api.routes import eda_router, graphs_router, strategies_router
from api.routes.graphs import _maybe_llm
from api.runtime import get_ner


class _FakeNer(NerProtocol):
    def __init__(self, by_text: dict[str, list[EntityMention]]) -> None:
        self._by_text = by_text

    def extract(self, text: str) -> list[EntityMention]:
        return list(self._by_text.get(text, ()))


class _FakeLLM(CompletionClient):
    provider = "fake"
    default_model = "fake-1"

    async def complete(
        self,
        messages: list[Message],
        params: CompletionParams | None = None,
    ) -> CompletionResult:
        return CompletionResult(
            text='{"merge": false, "reason": "test"}', model=self.default_model
        )


@pytest.fixture
def app() -> FastAPI:
    a = FastAPI()
    a.include_router(strategies_router)
    a.include_router(eda_router)
    a.include_router(graphs_router)
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ---- Strategy catalog ----


def test_get_strategies_aggregator(client: TestClient) -> None:
    resp = client.get("/api/strategies")
    assert resp.status_code == 200
    payload = resp.json()
    assert {"builder", "cleaner", "clusterer", "reasoner"}.issubset(payload.keys())
    assert any(d["name"] == "ner_extraction" for d in payload["builder"])
    assert any(d["name"] == "threshold_prune" for d in payload["cleaner"])
    assert any(d["name"] == "leiden" for d in payload["clusterer"])
    assert any(d["name"] == "keyword_search" for d in payload["reasoner"])


@pytest.mark.parametrize(
    "kind,expected_name",
    [
        ("builders", "ner_extraction"),
        ("cleaners", "threshold_prune"),
        ("clusterers", "leiden"),
        ("reasoners", "keyword_search"),
    ],
)
def test_per_kind_listing(client: TestClient, kind: str, expected_name: str) -> None:
    resp = client.get(f"/api/{kind}")
    assert resp.status_code == 200
    names = [d["name"] for d in resp.json()]
    assert expected_name in names


def test_describe_known_strategy(client: TestClient) -> None:
    resp = client.get("/api/strategies/builder/ner_extraction")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "ner_extraction"
    assert body["kind"] == "builder"
    assert "produces_layers" in body


def test_describe_unknown_strategy_404(client: TestClient) -> None:
    resp = client.get("/api/strategies/builder/does_not_exist")
    assert resp.status_code == 404


def test_describe_unknown_kind_rejected(client: TestClient) -> None:
    """Path param is typed Literal[Kind], so FastAPI validates it
    before the handler runs and returns 422 — that's fine for our use
    case (the wizard always sends a known kind).
    """

    resp = client.get("/api/strategies/wizard/x")
    assert resp.status_code == 422


# ---- EDA endpoint ----


def test_eda_returns_report(app: FastAPI, client: TestClient) -> None:
    fake_ner = _FakeNer(
        {
            "Иванов работает в ВШЭ": [
                EntityMention(text="Иванов", lemma="иванов", type="PER", start=0, end=6),
                EntityMention(text="ВШЭ", lemma="вшэ", type="ORG", start=18, end=21),
            ]
        }
    )
    app.dependency_overrides[get_ner] = lambda: fake_ner

    payload = {
        "documents": [
            {"text": "Иванов работает в ВШЭ"},
            {"text": "Иванов работает в ВШЭ"},
            {"text": "Иванов работает в ВШЭ"},
        ]
    }
    resp = client.post("/api/eda", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["document_stats"]["document_count"] == 3
    assert body["recommendation"]["builder"]
    assert body["recommendation"]["clusterer"]


def test_eda_rejects_empty_documents(client: TestClient) -> None:
    resp = client.post("/api/eda", json={"documents": []})
    assert resp.status_code in (400, 422)  # FastAPI may catch via Pydantic


def test_eda_recommendation_passes_registry_validation(
    app: FastAPI, client: TestClient
) -> None:
    """Phase 1.7: EDA's default recommendation references real registered
    plugin names; no warning gets appended.
    """

    fake_ner = _FakeNer(
        {
            "doc": [
                EntityMention(text="Иванов", lemma="иванов", type="PER", start=0, end=6)
            ]
        }
    )
    app.dependency_overrides[get_ner] = lambda: fake_ner

    resp = client.post("/api/eda", json={"documents": [{"text": "doc"}]})
    assert resp.status_code == 200
    rationale = resp.json()["recommendation"]["rationale"]
    assert "ВНИМАНИЕ" not in rationale  # all names valid


# ---- /api/graphs/preview ----


def test_preview_runs_ner_pipeline_end_to_end(
    app: FastAPI, client: TestClient
) -> None:
    fake_ner = _FakeNer(
        {
            "Иванов и Петров работают в ВШЭ.": [
                EntityMention(text="Иванов", lemma="иванов", type="PER", start=0, end=6),
                EntityMention(text="Петров", lemma="петров", type="PER", start=9, end=15),
            ]
        }
    )
    app.dependency_overrides[get_ner] = lambda: fake_ner
    app.dependency_overrides[_maybe_llm] = lambda: None  # llm_dedup not exercised

    resp = client.post(
        "/api/graphs/preview",
        json={
            "documents": [
                {"title": "doc", "text": "Иванов и Петров работают в ВШЭ."},
            ],
            "builder": "ner_extraction",
            "cleaner_chain": ["threshold_prune"],
            "clusterer": "leiden",
            "builder_params": {"chunk_size": 1500},
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["node_count"] > 0
    # Builder produced chunk + entity layers; clusterer added community.
    assert {"chunk", "entity", "community"}.issubset(body["nodes_by_layer"].keys())
    assert body["graph_variant_id"]


def test_preview_rejects_unknown_builder(app: FastAPI, client: TestClient) -> None:
    fake_ner = _FakeNer({})
    app.dependency_overrides[get_ner] = lambda: fake_ner
    app.dependency_overrides[_maybe_llm] = lambda: None

    resp = client.post(
        "/api/graphs/preview",
        json={
            "documents": [{"title": "x", "text": "x"}],
            "builder": "does_not_exist",
        },
    )
    assert resp.status_code == 400
    assert "does_not_exist" in resp.json()["detail"]


def test_preview_passes_through_not_implemented_as_501(
    app: FastAPI, client: TestClient
) -> None:
    """Microsoft/LightRAG/ToG3 builders raise NotImplementedError; the
    handler should surface this as 501 so the wizard distinguishes
    'unknown plugin' from 'plugin known but not wired yet'.
    """

    fake_ner = _FakeNer({})
    app.dependency_overrides[get_ner] = lambda: fake_ner
    app.dependency_overrides[_maybe_llm] = lambda: None

    resp = client.post(
        "/api/graphs/preview",
        json={
            "documents": [{"title": "x", "text": "x"}],
            "builder": "lightrag",
        },
    )
    assert resp.status_code == 501


def test_preview_with_llm_dedup_uses_injected_llm(
    app: FastAPI, client: TestClient
) -> None:
    """Builder dedups entities by (type, lemma); cleaner buckets by
    (type, first-token of name). Distinct lemmas + shared first token
    is what produces a candidate pair the LLM gets to vote on.
    """

    fake_ner = _FakeNer(
        {
            "Иванов И. и Иванов А.": [
                EntityMention(text="Иванов И.", lemma="иванов_и", type="PER", start=0, end=9),
                EntityMention(text="Иванов А.", lemma="иванов_а", type="PER", start=14, end=23),
            ]
        }
    )
    app.dependency_overrides[get_ner] = lambda: fake_ner
    app.dependency_overrides[_maybe_llm] = lambda: _FakeLLM()

    resp = client.post(
        "/api/graphs/preview",
        json={
            "documents": [{"title": "doc", "text": "Иванов И. и Иванов А."}],
            "builder": "ner_extraction",
            "cleaner_chain": ["llm_dedup"],
        },
    )
    assert resp.status_code == 200, resp.text
    # Fake LLM always answers "no merge" → both entities survive.
    assert resp.json()["nodes_by_layer"]["entity"] == 2
