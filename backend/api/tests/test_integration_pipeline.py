"""Integration tests for the GraphRAG Explorer R2 backend.

Covers cross-router workflows the per-router suites don't exercise:
  * full corpus → eda → build → agent → accept → reason journey
  * the assembled `api.__main__:app` (all routers + startup hook)
  * lifecycle / version / journal / undo consistency
  * filter combos and 404/409/422 contract integrity
  * auth-cookie + curation interplay

See `integration_test_plan.md` for the test-by-test mapping.
"""

from __future__ import annotations

import csv
import io
import json
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.agents  # noqa: F401  — populates agent registry
import api.strategies.aggregators  # noqa: F401
import api.strategies.builders  # noqa: F401
import api.strategies.cleaners  # noqa: F401
import api.strategies.clusterers  # noqa: F401
import api.strategies.reasoners  # noqa: F401
import api.tools  # noqa: F401
from api.eda.ner import EntityMention, NerProtocol
from api.llm import CompletionClient, CompletionParams, CompletionResult, Message
from api.repository import InMemoryRepository
from api.routes import (
    agents_router,
    auth_router,
    corpora_router,
    eda_router,
    graphs_router,
    journal_export_router,
    reason_router,
    strategies_router,
    tools_router,
)
from api.routes.graphs import _maybe_llm
from api.runtime import get_ner, get_repository


# ---------- shared fixtures ----------


_DEMO_TEXT = "Иванов работает в ВШЭ. Иванов знаком с Петровым. ВШЭ - университет."


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
            text='{"merge": false, "reason": "stub"}', model=self.default_model
        )


def _demo_mentions() -> dict[str, list[EntityMention]]:
    return {
        _DEMO_TEXT: [
            EntityMention(text="Иванов", lemma="иванов", type="PER", start=0, end=6),
            EntityMention(text="ВШЭ", lemma="вшэ", type="ORG", start=18, end=21),
            EntityMention(text="Иванов", lemma="иванов", type="PER", start=23, end=29),
            EntityMention(text="Петровым", lemma="петров", type="PER", start=39, end=47),
            EntityMention(text="ВШЭ", lemma="вшэ", type="ORG", start=49, end=52),
        ]
    }


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture
def fake_ner() -> _FakeNer:
    return _FakeNer(_demo_mentions())


@pytest.fixture
def app(repo: InMemoryRepository, fake_ner: _FakeNer) -> FastAPI:
    """Single FastAPI with **all** routers wired — cross-router tests
    don't have to mount each router individually like per-router suites
    do.
    """

    a = FastAPI()
    a.include_router(strategies_router)
    a.include_router(corpora_router)
    a.include_router(eda_router)
    a.include_router(graphs_router)
    a.include_router(agents_router)
    a.include_router(reason_router)
    a.include_router(journal_export_router)
    a.include_router(tools_router)
    a.include_router(auth_router)
    a.dependency_overrides[get_repository] = lambda: repo
    a.dependency_overrides[get_ner] = lambda: fake_ner
    a.dependency_overrides[_maybe_llm] = lambda: None
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _seed_corpus_and_doc(client: TestClient) -> tuple[str, str]:
    cid = client.post("/api/corpora", json={"name": "demo"}).json()["id"]
    doc = client.post(
        f"/api/corpora/{cid}/documents",
        json={"title": "ep1", "text": _DEMO_TEXT},
    ).json()
    return cid, doc["id"]


def _build_variant(client: TestClient, corpus_id: str, name: str = "v") -> dict:
    resp = client.post(
        f"/api/corpora/{corpus_id}/graphs",
        json={
            "name": name,
            "builder": "ner_extraction",
            "cleaner_chain": ["threshold_prune"],
            "clusterer": "leiden",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# =====================================================================
# Group A — real assembled app smoke
# =====================================================================


def test_A1_health_via_real_app() -> None:
    """The shipped `api.__main__:app` boots, mounts all routers, and the
    /api/health indicator picks one of the documented backends.
    """

    from api.__main__ import app as real_app

    client = TestClient(real_app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["persistence"] in {"snapshot", "postgres", "in_memory"}


def test_A2_strategies_aggregator_all_kinds_populated() -> None:
    """The /api/strategies aggregator must surface at least one of every
    strategy kind once the package-level imports have run. Regression
    guard: forgetting an `import api.strategies.x` in a route module
    silently empties the catalog and the wizard goes blank.
    """

    from api.__main__ import app as real_app

    client = TestClient(real_app)
    payload = client.get("/api/strategies").json()
    for kind in ("builder", "cleaner", "clusterer", "reasoner", "aggregator", "agent"):
        assert payload.get(kind), f"strategy kind {kind!r} is empty"


def test_A3_eda_recommendation_references_registered_strategies(
    client: TestClient,
) -> None:
    """Cross-router check: every plugin name EDA recommends must exist
    in the strategies catalog (otherwise the wizard pre-fill is stale
    and the user gets a 400 on Build). The EDA route logs a warning in
    rationale on mismatch — we assert no warning + each name resolves
    via /api/strategies/{kind}/{name}.
    """

    cid, _ = _seed_corpus_and_doc(client)
    eda = client.post(
        "/api/eda",
        json={"corpus_id": cid, "documents": [{"text": _DEMO_TEXT}]},
    )
    assert eda.status_code == 200, eda.text
    rec = eda.json()["recommendation"]

    assert "ВНИМАНИЕ" not in rec["rationale"], rec["rationale"]
    assert (
        client.get(f"/api/strategies/builder/{rec['builder']}").status_code == 200
    )
    for name in rec["cleaner_chain"]:
        assert client.get(f"/api/strategies/cleaner/{name}").status_code == 200
    if rec.get("clusterer"):
        assert (
            client.get(
                f"/api/strategies/clusterer/{rec['clusterer']}"
            ).status_code
            == 200
        )


# =====================================================================
# Group B — full journey
# =====================================================================


def test_B1_full_journey_corpus_to_reason(client: TestClient) -> None:
    """corpus → docs → eda → preview → build → state → reason. Each step
    feeds the next; failure here indicates a wire-up bug between routers.
    """

    cid, doc_id = _seed_corpus_and_doc(client)

    eda = client.post(
        "/api/eda",
        json={"corpus_id": cid, "documents": [{"text": _DEMO_TEXT}]},
    ).json()
    assert eda["recommendation"]["builder"]

    preview = client.post(
        "/api/graphs/preview",
        json={
            "corpus_id": cid,
            "documents": [{"title": "ep1", "text": _DEMO_TEXT}],
            "builder": "ner_extraction",
            "cleaner_chain": ["threshold_prune"],
            "clusterer": "leiden",
        },
    ).json()
    assert preview["node_count"] > 0

    variant = _build_variant(client, cid)
    assert variant["status"] == "ready"

    state = client.get(f"/api/graphs/{variant['id']}/state").json()
    assert state["node_count"] == variant["node_count"]
    assert state["version"] == 0

    reason = client.post(
        "/api/reason",
        json={
            "mode": "single",
            "query": "Иванов",
            "variant_ids": [variant["id"]],
            "reasoner": "keyword_search",
        },
    )
    assert reason.status_code == 200, reason.text
    body = reason.json()
    assert "answer" in body
    assert isinstance(body["answer"]["text"], str)
    assert len(body["experts"]) == 1
    assert body["experts"][0]["variant_id"] == variant["id"]


def test_B2_journey_two_variants_then_moe(client: TestClient) -> None:
    """Two variants over the same corpus → MoE evidence_union picks up
    blocks from both; list filter scoped to the corpus is consistent.
    """

    cid, _ = _seed_corpus_and_doc(client)
    v1 = _build_variant(client, cid, name="v-baseline")
    v2 = _build_variant(client, cid, name="v-clustered")

    listed = client.get(f"/api/graphs?corpus_id={cid}").json()
    listed_ids = {v["id"] for v in listed}
    assert {v1["id"], v2["id"]}.issubset(listed_ids)

    moe = client.post(
        "/api/reason",
        json={
            "mode": "moe",
            "query": "ВШЭ",
            "variant_ids": [v1["id"], v2["id"]],
            "reasoner": "keyword_search",
            "aggregator": "evidence_union",
        },
    )
    assert moe.status_code == 200, moe.text
    body = moe.json()
    assert body["aggregator"] == "evidence_union"
    assert len(body["experts"]) == 2
    expert_variants = {e["variant_id"] for e in body["experts"]}
    assert expert_variants == {v1["id"], v2["id"]}


def test_B3_journey_agent_proposes_then_accept_increments_version(
    client: TestClient,
) -> None:
    """Agent run → suggestion → accept → variant.version+=1 + journal
    entry exists. Tests the full curation feedback loop.
    """

    cid, _ = _seed_corpus_and_doc(client)
    variant = _build_variant(client, cid)
    vid = variant["id"]

    run = client.post(
        f"/api/graphs/{vid}/agents/orphan_rescuer/run",
        json={"params": {"min_total_degree_to_skip": 100}},
    )
    assert run.status_code == 200, run.text
    suggestions = run.json()["suggestions"]
    assert suggestions, "fixture must produce at least one orphan candidate"

    state_before = client.get(f"/api/graphs/{vid}/state").json()
    accept = client.post(
        f"/api/suggestions/{suggestions[0]['id']}/accept",
        json={
            "expected_variant_version": state_before["version"],
            "actor": "user:integration",
        },
    )
    assert accept.status_code == 200, accept.text
    body = accept.json()
    assert body["variant"]["version"] == state_before["version"] + 1

    journal = client.get(f"/api/graphs/{vid}/journal").json()
    assert any(e["actor"] == "user:integration" for e in journal)


def test_B4_journey_multiple_undo_pops_one_at_a_time(
    client: TestClient,
) -> None:
    """3 ops applied; 2 undo calls pop the 2 most-recent, version keeps
    incrementing (undo is recorded as an inverse op, not a rollback).
    Exercises the journal applier's invariant under repeated undo.
    """

    cid, _ = _seed_corpus_and_doc(client)
    variant = _build_variant(client, cid)
    vid = variant["id"]

    # Pull a real entity-layer node id from the in-memory repo to use
    # as the target of update_node_name ops.
    target_id = _first_entity_id(client, vid)

    versions: list[int] = [0]
    for i, name in enumerate(["A", "B", "C"]):
        resp = client.post(
            f"/api/graphs/{vid}/journal",
            json={
                "op": "update_node_name",
                "payload": {"node_id": target_id, "name": name},
                "expected_version": versions[-1],
                "actor": f"user:test-{i}",
            },
        )
        assert resp.status_code == 200, resp.text
        versions.append(resp.json()["variant"]["version"])

    assert versions == [0, 1, 2, 3]

    # Two undos. Each undo bumps version by 1 and pops one journal entry.
    for _ in range(2):
        cur = client.get(f"/api/graphs/{vid}/state").json()
        u = client.post(
            f"/api/graphs/{vid}/undo",
            json={"expected_version": cur["version"]},
        )
        assert u.status_code == 200, u.text

    final = client.get(f"/api/graphs/{vid}/journal").json()
    assert len(final) == 1  # 3 appended − 2 undone (undos pop journal)
    assert final[0]["payload"]["name"] == "A"


# =====================================================================
# Group C — cross-router consistency
# =====================================================================


def test_C1_journal_export_csv_contains_appended_op(
    client: TestClient,
) -> None:
    """Append an op via /journal, fetch /journal/export?format=csv. The
    CSV must round-trip the op + actor.
    """

    cid, _ = _seed_corpus_and_doc(client)
    vid = _build_variant(client, cid)["id"]
    target_id = _first_entity_id(client, vid)
    client.post(
        f"/api/graphs/{vid}/journal",
        json={
            "op": "update_node_name",
            "payload": {"node_id": target_id, "name": "Renamed"},
            "expected_version": 0,
            "actor": "user:csv",
        },
    )

    resp = client.get(f"/api/graphs/{vid}/journal/export?format=csv")
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8"))))
    assert rows[0][2] == "op"
    body = rows[1:]
    assert any(r[2] == "update_node_name" and r[3] == "user:csv" for r in body)


def test_C2_journal_export_json_round_trips_payloads(
    client: TestClient,
) -> None:
    """JSON export must preserve payload keys verbatim."""

    cid, _ = _seed_corpus_and_doc(client)
    vid = _build_variant(client, cid)["id"]
    target_id = _first_entity_id(client, vid)
    client.post(
        f"/api/graphs/{vid}/journal",
        json={
            "op": "set_summary",
            "payload": {"node_id": target_id, "summary": "test summary"},
            "expected_version": 0,
            "actor": "user:json",
        },
    )

    resp = client.get(f"/api/graphs/{vid}/journal/export?format=json")
    assert resp.status_code == 200
    payload = json.loads(resp.content)
    assert isinstance(payload, list)
    entry = next(e for e in payload if e["op"] == "set_summary")
    assert entry["payload"]["summary"] == "test summary"
    assert entry["payload"]["node_id"] == target_id


def test_C3_tool_invocation_persists_and_lists(client: TestClient) -> None:
    """Run a tool on a real persisted node, then list invocations: the
    history must contain the run with matching arguments + tool name.
    """

    cid, _ = _seed_corpus_and_doc(client)
    vid = _build_variant(client, cid)["id"]
    node_id = _first_entity_id(client, vid)

    run = client.post(
        f"/api/nodes/{vid}/{node_id}/tools/show_neighbors/run",
        json={"params": {"depth": 1}},
    )
    assert run.status_code == 200, run.text
    inv = run.json()
    assert inv["tool"] == "show_neighbors"

    history = client.get(f"/api/nodes/{vid}/{node_id}/tool_invocations").json()
    assert len(history) == 1
    assert history[0]["id"] == inv["id"]
    assert history[0]["arguments"] == {"depth": 1}


def test_C4_drill_down_document_text_survives_build(client: TestClient) -> None:
    """The document drill-down route (recently added) must keep the full
    text reachable after the corpus has been built into a variant —
    regression guard for accidentally stripping `text` during ingest.
    """

    cid, doc_id = _seed_corpus_and_doc(client)
    _build_variant(client, cid)

    fetched = client.get(f"/api/corpora/{cid}/documents/{doc_id}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["text"] == _DEMO_TEXT


# =====================================================================
# Group D — filters & pagination
# =====================================================================


def test_D1_list_variants_filters_by_corpus_id(client: TestClient) -> None:
    cid_a, _ = _seed_corpus_and_doc(client)
    cid_b = client.post("/api/corpora", json={"name": "b"}).json()["id"]
    client.post(
        f"/api/corpora/{cid_b}/documents",
        json={"title": "ep", "text": _DEMO_TEXT},
    )
    va = _build_variant(client, cid_a, name="va")
    vb = _build_variant(client, cid_b, name="vb")

    only_a = client.get(f"/api/graphs?corpus_id={cid_a}").json()
    a_ids = {v["id"] for v in only_a}
    assert va["id"] in a_ids
    assert vb["id"] not in a_ids


def test_D2_list_nodes_layer_filter_returns_only_layer(
    client: TestClient,
) -> None:
    cid, _ = _seed_corpus_and_doc(client)
    vid = _build_variant(client, cid)["id"]

    entities = client.get(f"/api/graphs/{vid}/nodes?layer=entity").json()
    assert entities, "expected at least one entity-layer node in fixture"
    assert all(n["layer"] == "entity" for n in entities)

    chunks = client.get(f"/api/graphs/{vid}/nodes?layer=chunk").json()
    assert all(n["layer"] == "chunk" for n in chunks)


def test_D3_list_journal_respects_limit(client: TestClient) -> None:
    cid, _ = _seed_corpus_and_doc(client)
    vid = _build_variant(client, cid)["id"]
    target_id = _first_entity_id(client, vid)

    for i, n in enumerate(["A", "B", "C"]):
        client.post(
            f"/api/graphs/{vid}/journal",
            json={
                "op": "update_node_name",
                "payload": {"node_id": target_id, "name": n},
                "expected_version": i,
                "actor": "user:test",
            },
        )

    full = client.get(f"/api/graphs/{vid}/journal").json()
    assert len(full) == 3
    capped = client.get(f"/api/graphs/{vid}/journal?limit=2").json()
    assert len(capped) == 2


def test_D4_list_suggestions_filter_status_and_agent(
    client: TestClient,
) -> None:
    cid, _ = _seed_corpus_and_doc(client)
    vid = _build_variant(client, cid)["id"]

    rescued = client.post(
        f"/api/graphs/{vid}/agents/orphan_rescuer/run",
        json={"params": {"min_total_degree_to_skip": 100}},
    ).json()["suggestions"]
    assert rescued, "fixture must produce orphan suggestions"
    sid = rescued[0]["id"]

    client.post(f"/api/suggestions/{sid}/reject", json={"actor": "user:test"})

    rejected_orphans = client.get(
        f"/api/graphs/{vid}/suggestions?status=rejected&agent=orphan_rescuer"
    ).json()
    assert all(
        s["status"] == "rejected" and s["agent"] == "orphan_rescuer"
        for s in rejected_orphans
    )
    assert any(s["id"] == sid for s in rejected_orphans)

    pending_orphans = client.get(
        f"/api/graphs/{vid}/suggestions?status=pending&agent=orphan_rescuer"
    ).json()
    assert all(s["id"] != sid for s in pending_orphans)


# =====================================================================
# Group E — error contracts
# =====================================================================


def test_E1_unknown_variant_id_returns_404_consistently(
    client: TestClient,
) -> None:
    """Every variant-prefixed endpoint must 404 (not 500, not 422) when
    the UUID is well-formed but not in the repo.
    """

    bogus = str(uuid4())
    paths = [
        f"/api/graphs/{bogus}",
        f"/api/graphs/{bogus}/state",
        f"/api/graphs/{bogus}/journal/export",
    ]
    for p in paths:
        r = client.get(p)
        assert r.status_code == 404, f"{p} returned {r.status_code}"


def test_E2_journal_append_payload_validation(client: TestClient) -> None:
    """An empty/invalid payload for any op must 422 — not 500. Each op
    has its own model, so we sample three to hit different validators.
    """

    cid, _ = _seed_corpus_and_doc(client)
    vid = _build_variant(client, cid)["id"]

    cases = [
        ("merge_nodes", {"absorbed_ids": []}),  # missing survivor_id
        ("set_summary", {}),  # missing both fields
        ("update_node_name", {"node_id": "not-a-uuid", "name": "x"}),
    ]
    for op, payload in cases:
        r = client.post(
            f"/api/graphs/{vid}/journal",
            json={
                "op": op,
                "payload": payload,
                "expected_version": 0,
                "actor": "user:test",
            },
        )
        assert r.status_code == 422, f"{op} returned {r.status_code}: {r.text}"


def test_E3_concurrent_accept_returns_409(client: TestClient) -> None:
    """Two accept races: first wins, second sees stale version → 409
    via the same ConcurrentEditError contract as raw journal append.
    """

    cid, _ = _seed_corpus_and_doc(client)
    vid = _build_variant(client, cid)["id"]
    sugs = client.post(
        f"/api/graphs/{vid}/agents/orphan_rescuer/run",
        json={"params": {"min_total_degree_to_skip": 100}},
    ).json()["suggestions"]
    assert len(sugs) >= 2, "fixture must produce ≥2 suggestions to race accepts"

    state_before = client.get(f"/api/graphs/{vid}/state").json()
    a = client.post(
        f"/api/suggestions/{sugs[0]['id']}/accept",
        json={
            "expected_variant_version": state_before["version"],
            "actor": "user:a",
        },
    )
    assert a.status_code == 200, a.text

    b = client.post(
        f"/api/suggestions/{sugs[1]['id']}/accept",
        json={
            "expected_variant_version": state_before["version"],  # stale now
            "actor": "user:b",
        },
    )
    assert b.status_code == 409, b.text


def test_E4_invalid_journal_export_format_returns_422(
    client: TestClient,
) -> None:
    cid, _ = _seed_corpus_and_doc(client)
    vid = _build_variant(client, cid)["id"]
    r = client.get(f"/api/graphs/{vid}/journal/export?format=xml")
    assert r.status_code == 422


# =====================================================================
# Group F — auth + curation interplay
# =====================================================================


def test_F1_logged_in_user_can_use_curation_routes(client: TestClient) -> None:
    """Curation routes are still optional-auth (Phase 1 default), so
    the ask is weaker: register doesn't break anything else, and a
    logged-in client still gets normal corpus-CRUD behavior.
    """

    email = f"curator+{uuid4().hex[:6]}@example.com"
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": "supersecret123", "language": "ru"},
    )
    assert r.status_code == 201, r.text
    assert "auth" in r.cookies

    # Same cookie jar is reused — just hit a curation route.
    cid = client.post("/api/corpora", json={"name": "auth-c"}).json()["id"]
    me = client.get("/api/auth/me").json()
    assert me["email"] == email
    assert client.get(f"/api/corpora/{cid}").status_code == 200


def test_F2_patch_language_persists(client: TestClient) -> None:
    email = f"lang+{uuid4().hex[:6]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "supersecret123", "language": "ru"},
    )
    patched = client.patch("/api/auth/me", json={"language": "en"})
    assert patched.status_code == 200
    assert patched.json()["language"] == "en"

    refreshed = client.get("/api/auth/me").json()
    assert refreshed["language"] == "en"


# ---------- helpers ----------


def _first_entity_id(client: TestClient, variant_id: str) -> str:
    """Reach into the repo via the dependency override to find a
    real entity-layer node id. The /api/graphs/{id}/nodes route also
    works for this — kept as a separate helper so the test reads
    closer to the (smaller) production usage.
    """

    nodes = client.get(f"/api/graphs/{variant_id}/nodes?layer=entity").json()
    assert nodes, f"variant {variant_id} has no entity nodes — fixture broken"
    return nodes[0]["id"]
