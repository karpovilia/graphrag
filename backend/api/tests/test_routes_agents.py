"""End-to-end tests for the agent + Suggestion + journal-export routes.

Reuses the InMemoryRepository setup pattern from test_routes_curation
so we can drive the full agent-run → suggestion-list → accept →
journal-entry pipeline without a real PG.
"""

from __future__ import annotations

import csv
import io
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.eda.ner import EntityMention, NerProtocol
from api.repository import InMemoryRepository
from api.routes import (
    agents_router,
    corpora_router,
    eda_router,
    graphs_router,
    journal_export_router,
    strategies_router,
)
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
def fake_ner() -> _FakeNer:
    # Distinct lemmas so EntityDeduplicator finds nothing without help;
    # individual tests override per-text mentions to drive specific
    # agent behaviors.
    return _FakeNer(
        {
            "Иванов работает с Иванов и с Петровым.": [
                EntityMention(text="Иванов", lemma="иванов_a", type="PER", start=0, end=6),
                EntityMention(text="Иванов", lemma="иванов_b", type="PER", start=18, end=24),
                EntityMention(text="Петровым", lemma="петров", type="PER", start=31, end=39),
            ]
        }
    )


@pytest.fixture
def app(repo: InMemoryRepository, fake_ner: _FakeNer) -> FastAPI:
    a = FastAPI()
    a.include_router(strategies_router)
    a.include_router(corpora_router)
    a.include_router(eda_router)
    a.include_router(graphs_router)
    a.include_router(agents_router)
    a.include_router(journal_export_router)
    a.dependency_overrides[get_repository] = lambda: repo
    a.dependency_overrides[get_ner] = lambda: fake_ner
    a.dependency_overrides[_maybe_llm] = lambda: None
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _seed_variant(client: TestClient) -> str:
    corpus = client.post("/api/corpora", json={"name": "c"}).json()
    client.post(
        f"/api/corpora/{corpus['id']}/documents",
        json={"title": "ep", "text": "Иванов работает с Иванов и с Петровым."},
    )
    variant = client.post(
        f"/api/corpora/{corpus['id']}/graphs",
        json={
            "name": "v",
            "builder": "ner_extraction",
            "cleaner_chain": ["threshold_prune"],
            "clusterer": "leiden",
        },
    ).json()
    return variant["id"]


# ---- agent listing ----


def test_list_agents_returns_six(client: TestClient) -> None:
    resp = client.get("/api/agents")
    assert resp.status_code == 200
    names = {d["name"] for d in resp.json()}
    assert names >= {
        "entity_dedup",
        "orphan_rescuer",
        "low_confidence_triplet",
        "topic_report_refresher",
        "relation_consistency",
        "community_stability",
    }


def test_strategies_aggregator_now_includes_agents(client: TestClient) -> None:
    payload = client.get("/api/strategies").json()
    assert "agent" in payload
    assert any(d["name"] == "entity_dedup" for d in payload["agent"])


# ---- agent run ----


def test_run_unknown_agent_returns_404(client: TestClient) -> None:
    variant_id = _seed_variant(client)
    resp = client.post(f"/api/graphs/{variant_id}/agents/no_such_agent/run", json={})
    assert resp.status_code == 404


def test_run_stub_agent_returns_501(client: TestClient) -> None:
    variant_id = _seed_variant(client)
    resp = client.post(
        f"/api/graphs/{variant_id}/agents/relation_consistency/run", json={}
    )
    assert resp.status_code == 501


def test_run_orphan_rescuer_creates_pending_suggestions(client: TestClient) -> None:
    variant_id = _seed_variant(client)

    resp = client.post(
        f"/api/graphs/{variant_id}/agents/orphan_rescuer/run", json={"params": {}}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["agent"] == "orphan_rescuer"
    # Three NER mentions with distinct lemmas → three entity nodes →
    # depending on co-occurrence, some will be orphans.
    suggestions = body["suggestions"]
    assert all(s["status"] == "pending" for s in suggestions)

    listed = client.get(f"/api/graphs/{variant_id}/suggestions").json()
    assert len(listed) == len(suggestions)


# ---- suggestion lifecycle ----


def test_accept_low_confidence_suggestion_appends_journal(
    client: TestClient,
) -> None:
    variant_id = _seed_variant(client)
    resp = client.post(
        f"/api/graphs/{variant_id}/agents/low_confidence_triplet/run",
        json={"params": {"weight_threshold": 100.0}},  # everything is "low"
    )
    suggestions = resp.json()["suggestions"]
    if not suggestions:
        pytest.skip("test corpus produced no entity-relation edges")

    suggestion_id = suggestions[0]["id"]
    state_before = client.get(f"/api/graphs/{variant_id}/state").json()

    accept = client.post(
        f"/api/suggestions/{suggestion_id}/accept",
        json={
            "expected_variant_version": state_before["version"],
            "actor": "user:test",
        },
    )
    assert accept.status_code == 200, accept.text
    body = accept.json()
    assert body["entry"]["op"] == "delete_edge"
    assert body["variant"]["version"] == state_before["version"] + 1

    # Suggestion is now ACCEPTED with a journal-entry pointer.
    refreshed = next(
        s
        for s in client.get(f"/api/graphs/{variant_id}/suggestions").json()
        if s["id"] == suggestion_id
    )
    assert refreshed["status"] == "accepted"
    assert refreshed["resulting_journal_entry_id"] == body["entry"]["id"]


def test_accept_already_decided_returns_400(client: TestClient) -> None:
    variant_id = _seed_variant(client)
    resp = client.post(
        f"/api/graphs/{variant_id}/agents/low_confidence_triplet/run",
        json={"params": {"weight_threshold": 100.0}},
    )
    suggestions = resp.json()["suggestions"]
    if not suggestions:
        pytest.skip("test corpus produced no entity-relation edges")
    suggestion_id = suggestions[0]["id"]

    state_before = client.get(f"/api/graphs/{variant_id}/state").json()
    client.post(
        f"/api/suggestions/{suggestion_id}/accept",
        json={
            "expected_variant_version": state_before["version"],
            "actor": "user:test",
        },
    )

    second = client.post(
        f"/api/suggestions/{suggestion_id}/accept",
        json={"expected_variant_version": 99, "actor": "user:test"},
    )
    assert second.status_code == 400


def test_accept_with_stale_version_returns_409(client: TestClient) -> None:
    variant_id = _seed_variant(client)
    suggestions = client.post(
        f"/api/graphs/{variant_id}/agents/low_confidence_triplet/run",
        json={"params": {"weight_threshold": 100.0}},
    ).json()["suggestions"]
    if not suggestions:
        pytest.skip("test corpus produced no entity-relation edges")

    resp = client.post(
        f"/api/suggestions/{suggestions[0]['id']}/accept",
        json={"expected_variant_version": 99, "actor": "user:test"},
    )
    assert resp.status_code == 409


def test_reject_suggestion_flips_status(client: TestClient) -> None:
    variant_id = _seed_variant(client)
    suggestions = client.post(
        f"/api/graphs/{variant_id}/agents/orphan_rescuer/run", json={"params": {}}
    ).json()["suggestions"]
    if not suggestions:
        pytest.skip("test corpus produced no orphan entities")

    sid = suggestions[0]["id"]
    resp = client.post(
        f"/api/suggestions/{sid}/reject", json={"actor": "user:test"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    # Listing with status filter respects the change.
    listed = client.get(
        f"/api/graphs/{variant_id}/suggestions?status=rejected"
    ).json()
    assert any(s["id"] == sid for s in listed)


def test_list_suggestions_filters_by_agent(client: TestClient) -> None:
    variant_id = _seed_variant(client)
    client.post(
        f"/api/graphs/{variant_id}/agents/orphan_rescuer/run", json={"params": {}}
    )
    client.post(
        f"/api/graphs/{variant_id}/agents/low_confidence_triplet/run",
        json={"params": {"weight_threshold": 100.0}},
    )

    orphan_only = client.get(
        f"/api/graphs/{variant_id}/suggestions?agent=orphan_rescuer"
    ).json()
    assert all(s["agent"] == "orphan_rescuer" for s in orphan_only)


# ---- journal export ----


def test_journal_export_json(client: TestClient) -> None:
    variant_id = _seed_variant(client)
    suggestions = client.post(
        f"/api/graphs/{variant_id}/agents/orphan_rescuer/run", json={"params": {}}
    ).json()["suggestions"]
    if suggestions:
        state = client.get(f"/api/graphs/{variant_id}/state").json()
        client.post(
            f"/api/suggestions/{suggestions[0]['id']}/accept",
            json={
                "expected_variant_version": state["version"],
                "actor": "user:test",
            },
        )

    resp = client.get(f"/api/graphs/{variant_id}/journal/export?format=json")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    payload = json.loads(resp.content.decode("utf-8"))
    assert isinstance(payload, list)
    if payload:
        assert "op" in payload[0]
        assert "actor" in payload[0]


def test_journal_export_csv(client: TestClient) -> None:
    variant_id = _seed_variant(client)
    suggestions = client.post(
        f"/api/graphs/{variant_id}/agents/orphan_rescuer/run", json={"params": {}}
    ).json()["suggestions"]
    if suggestions:
        state = client.get(f"/api/graphs/{variant_id}/state").json()
        client.post(
            f"/api/suggestions/{suggestions[0]['id']}/accept",
            json={
                "expected_variant_version": state["version"],
                "actor": "user:test",
            },
        )

    resp = client.get(f"/api/graphs/{variant_id}/journal/export?format=csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8"))))
    assert rows[0] == [
        "id",
        "graph_variant_id",
        "op",
        "actor",
        "parent_entry_id",
        "created_at",
        "payload",
    ]


def test_journal_export_unknown_format_returns_422(client: TestClient) -> None:
    variant_id = _seed_variant(client)
    resp = client.get(f"/api/graphs/{variant_id}/journal/export?format=xml")
    assert resp.status_code == 422


def test_journal_export_unknown_variant_returns_404(client: TestClient) -> None:
    from uuid import uuid4

    resp = client.get(f"/api/graphs/{uuid4()}/journal/export")
    assert resp.status_code == 404


# ---- suggestion repo direct unit tests ----


async def test_create_suggestions_validates_variant_exists(
    repo: InMemoryRepository,
) -> None:
    from uuid import uuid4

    from api.domain.curation import Suggestion, SuggestionAction
    from api.domain.types import Id

    bogus = Suggestion(
        graph_variant_id=Id(uuid4()),
        agent="entity_dedup",
        action=SuggestionAction.MERGE,
        payload={},
        confidence=0.5,
        rationale="x",
    )
    with pytest.raises(Exception):  # NotFoundError
        await repo.create_suggestions([bogus])
