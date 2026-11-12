"""Local accounts: Argon2id hashes, login, token expiry/revocation, refresh rotation + replay, disablement."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from app.auth.tokens import issue_access

from .conftest import PASSWORD, SECRET, Users


def _container(client: TestClient):  # noqa: ANN202
    return client.app.state.container  # type: ignore[attr-defined]


def test_first_account_is_owner_then_members_and_passwords_are_argon2(users: Users, secure_app: TestClient) -> None:
    first = users.register("owner@example.com")
    second = users.register("member@example.com")
    assert first.status_code == 201 and first.json()["role"] == "OWNER"
    assert second.json()["role"] == "MEMBER"
    assert "password" not in first.text and "hash" not in first.text
    row = secure_app.portal.call(_container(secure_app).persistence.users.by_email, "member@example.com")  # type: ignore[union-attr]
    assert row.password_hash.startswith("$argon2id$") and PASSWORD not in row.password_hash
    assert users.register("member@example.com").status_code == 409


def test_weak_password_and_disabled_registration(users: Users, secure_factory) -> None:  # noqa: ANN001
    assert users.register("weak@example.com", "short").status_code == 422
    closed = secure_factory(registration_enabled=False)
    assert closed.post("/api/v1/auth/register", json={"email": "x@example.com", "password": PASSWORD}).status_code == 403


def test_login_sets_httponly_cookies_and_never_returns_tokens(users: Users, secure_app: TestClient) -> None:
    users.register("a@example.com")
    r = secure_app.post("/api/v1/auth/login", json={"email": "a@example.com", "password": PASSWORD})
    assert r.status_code == 200
    body = r.text
    assert "tp_access" not in body and "refresh" not in body.lower().replace("access_expires_in", "")
    cookies = r.headers.get_list("set-cookie")
    access = next(c for c in cookies if c.startswith("tp_access="))
    refresh = next(c for c in cookies if c.startswith("tp_refresh="))
    assert "HttpOnly" in access and "HttpOnly" in refresh and "Path=/api/v1/auth" in refresh
    csrf = next(c for c in cookies if c.startswith("tp_csrf="))
    assert "HttpOnly" not in csrf


def test_invalid_password_unknown_user_and_unauthenticated_access(users: Users, secure_app: TestClient) -> None:
    users.register("b@example.com")
    assert secure_app.post("/api/v1/auth/login", json={"email": "b@example.com", "password": "Wrong-Password-1"}).status_code == 401
    assert secure_app.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}).status_code == 401
    secure_app.cookies.clear()
    r = secure_app.get("/api/v1/tasks?session_id=" + "0" * 8 + "-0000-4000-8000-" + "0" * 12)
    assert r.status_code == 401 and r.json()["code"] == "AUTHENTICATION_REQUIRED"
    assert secure_app.get("/api/v1/health/live").status_code == 200  # liveness stays public


def test_expired_and_forged_access_tokens(users: Users, secure_app: TestClient) -> None:
    actor = users.new("c@example.com")
    expired, _ = issue_access(SECRET, user_id=UUID(actor.user_id), role="MEMBER", version=0, csrf_token="x", ttl=timedelta(seconds=-5))
    secure_app.cookies.clear()
    r = secure_app.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_EXPIRED"
    forged, _ = issue_access("another-secret-entirely-0123456789-xyz", user_id=UUID(actor.user_id), role="OWNER", version=0,
                             csrf_token="x", ttl=timedelta(minutes=5))
    assert secure_app.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    assert users.get(actor, "/api/v1/auth/me").json()["email"] == "c@example.com"


def test_refresh_rotation_and_replay_revokes_the_family(users: Users, secure_app: TestClient) -> None:
    actor = users.new("d@example.com")
    old_refresh = actor.cookies["tp_refresh"]
    client = users.as_(actor)
    r1 = client.post("/api/v1/auth/refresh")
    assert r1.status_code == 200
    new_refresh = next(c.split(";", 1)[0].split("=", 1)[1] for c in r1.headers.get_list("set-cookie") if c.startswith("tp_refresh="))
    assert new_refresh and new_refresh != old_refresh
    # replaying the rotated token = theft signal: the whole family (incl. the new token) is revoked
    client.cookies.clear()
    client.cookies.set("tp_refresh", old_refresh, path="/api/v1/auth")
    replay = client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401 and replay.json()["code"] == "REFRESH_TOKEN_REUSED"
    client.cookies.clear()
    client.cookies.set("tp_refresh", new_refresh, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_logout_all_and_account_disablement_invalidate_tokens(users: Users, secure_app: TestClient) -> None:
    actor = users.new("e@example.com")
    assert users.post(actor, "/api/v1/auth/logout-all").status_code == 204
    assert users.get(actor, "/api/v1/auth/me").status_code == 401  # token version bumped
    actor = users.login("e@example.com")
    container = _container(secure_app)
    secure_app.portal.call(container.auth.disable, UUID(actor.user_id))  # type: ignore[union-attr]
    assert users.get(actor, "/api/v1/auth/me").status_code == 401
    r = secure_app.post("/api/v1/auth/login", json={"email": "e@example.com", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["code"] == "ACCOUNT_DISABLED"


def test_login_brute_force_is_throttled(users: Users, secure_app: TestClient) -> None:
    users.register("f@example.com")
    codes = [secure_app.post("/api/v1/auth/login", json={"email": "f@example.com", "password": "Nope-nope-123"}).status_code
             for _ in range(7)]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    # even the right password is refused while throttled
    assert secure_app.post("/api/v1/auth/login", json={"email": "f@example.com", "password": PASSWORD}).status_code == 429


def test_auth_events_are_audited(users: Users, secure_app: TestClient) -> None:
    users.new("g@example.com")
    rows = secure_app.portal.call(lambda: _container(secure_app).persistence.audit.page(user_id=None, after_seq=None, limit=50))  # type: ignore[union-attr]
    kinds = {(r.event_type, r.outcome) for r in rows}
    assert ("auth.register", "SUCCESS") in kinds and ("auth.login", "SUCCESS") in kinds
    assert all("password" not in str(r.metadata_json).lower() for r in rows)
