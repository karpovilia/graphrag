from __future__ import annotations

from fastapi.testclient import TestClient

from api.__main__ import app


def test_health_returns_ok_with_persistence_indicator() -> None:
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["persistence"] in {"snapshot", "postgres", "in_memory"}


def test_corpora_endpoint_reachable_on_empty_state() -> None:
    client = TestClient(app)
    resp = client.get("/api/corpora")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
