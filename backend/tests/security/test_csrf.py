"""CSRF: cookie-authenticated mutations need a header that matches the cookie AND the token-bound digest."""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import Users


def _create(client: TestClient, session_id: str, headers: dict[str, str]) -> int:
    return client.post("/api/v1/tasks", json={"command": "hello", "session_id": session_id, "input_mode": "TEXT"}, headers=headers).status_code


def test_missing_wrong_or_planted_csrf_tokens_are_refused(users: Users) -> None:
    a = users.new("csrf@example.com")
    client = users.as_(a)
    assert _create(client, a.session_id, {}) == 403
    assert _create(client, a.session_id, {"X-CSRF-Token": "guess"}) == 403
    # an attacker who can plant a cookie AND send a matching header still fails: the digest is bound in the token
    client.cookies.set("tp_csrf", "attacker-chosen")
    assert _create(client, a.session_id, {"X-CSRF-Token": "attacker-chosen"}) == 403
    assert _create(users.as_(a), a.session_id, a.headers()) == 202


def test_safe_methods_and_bearer_requests_are_not_subject_to_csrf(users: Users, secure_app: TestClient) -> None:
    a = users.new("bearer@example.com")
    assert users.get(a, "/api/v1/auth/me").status_code == 200
    token = a.cookies["tp_access"]
    secure_app.cookies.clear()
    r = secure_app.post("/api/v1/tasks", json={"command": "hello", "session_id": a.session_id, "input_mode": "TEXT"},
                        headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 202
