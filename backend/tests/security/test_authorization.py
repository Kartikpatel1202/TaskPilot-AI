"""Scenario 2 — authentication and isolation: every cross-user operation is rejected."""

from __future__ import annotations

import time
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.schemas.approval import RiskLevel
from app.schemas.common import utc_now
from app.schemas.files import DownloadedFile, DownloadStatus

from .conftest import Actor, Users


def _c(client: TestClient):  # noqa: ANN202
    return client.app.state.container  # type: ignore[attr-defined]


def _task(users: Users, actor: Actor, command: str = "Search for wireless earbuds on amazon") -> str:
    r = users.post(actor, "/api/v1/tasks", {"command": command, "session_id": actor.session_id, "input_mode": "TEXT"})
    assert r.status_code == 202, r.text
    task_id = r.json()["task_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = users.get(actor, f"/api/v1/tasks/{task_id}").json()["state"]
        if state in ("PLANNED", "NEEDS_CLARIFICATION", "FAILED"):
            break
        time.sleep(0.02)
    return task_id


def test_scenario2_user_b_cannot_touch_user_a(users: Users, secure_app: TestClient) -> None:
    a = users.new("alice@example.com")
    b = users.new("bob@example.com")
    task_id = _task(users, a)
    assert users.get(a, f"/api/v1/tasks/{task_id}").status_code == 200
    # read task / plan / execution / workflow
    for url in (f"/api/v1/tasks/{task_id}", f"/api/v1/tasks/{task_id}/plan", f"/api/v1/tasks/{task_id}/execution",
                f"/api/v1/tasks/{task_id}/plan?session_id={b.session_id}"):
        r = users.get(b, url)
        assert r.status_code == 403, (url, r.status_code)
    # use A's session id as B (query and body)
    assert users.get(b, f"/api/v1/tasks?session_id={a.session_id}").status_code == 403
    assert users.post(b, "/api/v1/tasks", {"command": "hello", "session_id": a.session_id, "input_mode": "TEXT"}).status_code == 403
    # stop / execute A's task
    assert users.post(b, f"/api/v1/tasks/{task_id}/stop", {"session_id": b.session_id, "reason": "x"}).status_code == 403
    assert users.post(b, f"/api/v1/tasks/{task_id}/execute", {"session_id": b.session_id, "confirm_execution": True}).status_code == 403
    # approve A's pending action
    approval = secure_app.portal.call(lambda: _c(secure_app).approvals.create(  # type: ignore[union-attr]
        task_id=UUID(task_id), session_id=UUID(a.session_id), action_summary="Do a thing", domain="example.com", reason="r",
        risk_level=RiskLevel.HIGH, ttl_seconds=60))
    r = users.post(b, f"/api/v1/approvals/{approval.approval_id}/decision", {"decision": "APPROVE"})
    assert r.status_code == 403
    assert _c(secure_app).approvals.get(approval.approval_id).status.value == "PENDING"
    # A's browser session / screenshot / memory (task history)
    assert users.get(b, f"/api/v1/browser/sessions/{a.session_id}").status_code == 403
    assert users.get(b, f"/api/v1/browser/sessions/{a.session_id}/screenshot").status_code == 403
    hist_b = users.get(b, "/api/v1/task-history").json()["tasks"]
    assert all(t["task_id"] != task_id for t in hist_b)
    assert any(t["task_id"] == task_id for t in users.get(a, "/api/v1/task-history").json()["tasks"])


def test_user_b_cannot_download_or_delete_user_a_file(users: Users, secure_app: TestClient) -> None:
    a = users.new("carol@example.com")
    b = users.new("dave@example.com")
    file_id = uuid4()
    meta = DownloadedFile(file_id=file_id, session_id=UUID(a.session_id), task_id=uuid4(), original_name="report.pdf",
                          stored_name=f"{file_id}.pdf", extension="pdf", mime_type="application/pdf", size_bytes=10, sha256="0" * 64,
                          source_domain="example.com", status=DownloadStatus.COMPLETED, created_at=utc_now(),
                          expires_at=utc_now() + timedelta(hours=1))

    async def seed() -> None:
        c = _c(secure_app)
        await c.persistence.sessions.claim(UUID(a.session_id), UUID(a.user_id))
        from app.database.models import TaskRecord

        async with c.persistence.db.session() as s:
            s.add(TaskRecord(id=meta.task_id, user_id=UUID(a.user_id), session_id=meta.session_id, command="x", input_mode="TEXT",
                             state="COMPLETED", created_at=utc_now(), updated_at=utc_now()))
        await c.persistence.files.add(meta, user_id=UUID(a.user_id), storage_key=f"k/{file_id}", scan_status="SCAN_UNAVAILABLE")

    secure_app.portal.call(seed)  # type: ignore[union-attr]
    assert users.get(b, f"/api/v1/files/{file_id}?session_id={b.session_id}").status_code == 403
    assert users.get(b, f"/api/v1/files/{file_id}/download?session_id={b.session_id}").status_code == 403
    assert users.delete(b, f"/api/v1/files/{file_id}", {"session_id": b.session_id, "confirm": True}).status_code == 403
    assert users.get(b, f"/api/v1/files?session_id={a.session_id}").status_code == 403


def test_read_only_accounts_cannot_mutate_and_audit_export_is_owner_only(users: Users, secure_app: TestClient) -> None:
    owner = users.new("owner2@example.com")
    member = users.new("member2@example.com")
    ro = users.new("viewer@example.com")
    secure_app.portal.call(_set_role, secure_app, UUID(ro.user_id), "READ_ONLY")  # type: ignore[union-attr]
    r = users.post(ro, "/api/v1/tasks", {"command": "hello", "session_id": ro.session_id, "input_mode": "TEXT"})
    assert r.status_code == 403 and r.json()["code"] == "READ_ONLY_ACCOUNT"
    assert users.get(ro, "/api/v1/task-history").status_code == 200
    assert users.get(member, "/api/v1/audit?all_users=true").status_code == 403
    assert users.get(member, "/api/v1/audit/verify").status_code == 403
    assert users.get(member, "/api/v1/health/details").status_code == 403
    assert users.get(owner, "/api/v1/audit?all_users=true").status_code == 200
    assert users.get(owner, "/api/v1/audit/verify").json()["intact"] is True
    assert users.get(owner, "/api/v1/health/details").status_code == 200


async def _set_role(client: TestClient, user_id: UUID, role: str) -> None:
    from sqlalchemy import update

    from app.database.models import UserRecord

    async with _c(client).persistence.db.session() as s:
        await s.execute(update(UserRecord).where(UserRecord.id == user_id).values(role=role))
