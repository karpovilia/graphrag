from __future__ import annotations

from fastapi.testclient import TestClient

from api.__main__ import app


def _client() -> TestClient:
    # Each test gets a fresh client with its own cookie jar; the shared
    # in-memory repo carries users across tests inside a single session,
    # which is fine — we use unique emails per test.
    return TestClient(app)


def test_register_and_login_flow_sets_auth_cookie() -> None:
    client = _client()
    email = "alice+register@example.com"

    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": "supersecret123", "language": "en"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == email
    assert body["language"] == "en"
    assert "password_hash" not in body
    assert "auth" in r.cookies

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == email


def test_login_with_wrong_password_returns_401() -> None:
    client = _client()
    email = "bob+wrongpw@example.com"

    client.post(
        "/api/auth/register",
        json={"email": email, "password": "correct-password", "language": "ru"},
    )
    fresh = _client()
    r = fresh.post(
        "/api/auth/login",
        json={"email": email, "password": "wrong-password"},
    )
    assert r.status_code == 401
    assert "auth" not in fresh.cookies


def test_register_duplicate_email_returns_409() -> None:
    client = _client()
    email = "carol+dup@example.com"
    p = {"email": email, "password": "anothersecret123", "language": "ru"}
    assert client.post("/api/auth/register", json=p).status_code == 201
    fresh = _client()
    r = fresh.post("/api/auth/register", json=p)
    assert r.status_code == 409


def test_me_without_cookie_returns_401() -> None:
    client = _client()
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_patch_me_updates_language() -> None:
    client = _client()
    email = "dave+patch@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "anothersecret123", "language": "ru"},
    )
    r = client.patch("/api/auth/me", json={"language": "en"})
    assert r.status_code == 200
    assert r.json()["language"] == "en"


def test_logout_clears_cookie() -> None:
    client = _client()
    email = "eve+logout@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "supersecret123", "language": "ru"},
    )
    assert client.get("/api/auth/me").status_code == 200
    r = client.post("/api/auth/logout")
    assert r.status_code == 204
    # The endpoint sent Set-Cookie with empty value + max-age=0; the
    # TestClient honours that and drops it.
    assert client.get("/api/auth/me").status_code == 401
