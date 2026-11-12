"""Session ids are bound to one account on first use; a known id never grants access."""

from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from .conftest import Users


def test_first_authenticated_use_binds_the_session(users: Users, secure_app: TestClient) -> None:
    a = users.new("s1@example.com")
    b = users.new("s2@example.com")
    assert users.get(a, f"/api/v1/tasks?session_id={a.session_id}").status_code == 200
    owner = secure_app.portal.call(secure_app.app.state.container.persistence.sessions.owner, UUID(a.session_id))  # type: ignore[union-attr]
    assert str(owner) == a.user_id
    r = users.get(b, f"/api/v1/tasks?session_id={a.session_id}")
    assert r.status_code == 403 and r.json()["code"] == "SESSION_ACCESS_DENIED"
    assert users.get(b, f"/api/v1/integrations/status?session_id={a.session_id}").status_code in (403, 503)


def test_telemetry_is_never_delivered_across_users(users: Users, secure_app: TestClient) -> None:
    a = users.new("s3@example.com")
    b = users.new("s4@example.com")
    users.post(a, "/api/v1/tasks", {"command": "hello there", "session_id": a.session_id, "input_mode": "TEXT"})
    history_b = secure_app.app.state.container.ws_manager.replay(UUID(b.session_id), None)[0]  # type: ignore[attr-defined]
    assert history_b == []
