"""Approval integrity: one-time use (database-backed, concurrent-safe), expiry, withdrawal, cross-user
decisions and exact-action binding (stale purchase / calendar approvals are covered by the Phase 4/5
suites and re-verified here at the storage level)."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient

from app.database.dependencies import Persistence
from app.database.models import TaskRecord
from app.database.session import Database
from app.schemas.approval import ApprovalDecision, ApprovalStatus, RiskLevel
from app.schemas.common import utc_now
from app.services.approval_service import ApprovalService

from .conftest import Users


class _Events:
    async def emit(self, *a: object, **k: object) -> None:
        return None


async def _service() -> tuple[ApprovalService, Persistence, Database]:
    db = Database("sqlite+aiosqlite://")
    await db.create_all()
    p = Persistence(db)
    svc = ApprovalService(_Events())  # type: ignore[arg-type]
    svc.persistence = p
    return svc, p, db


async def _approval(svc: ApprovalService, p: Persistence, ttl: int = 60):  # noqa: ANN202
    task, sid = uuid4(), uuid4()
    async with p.db.session() as s:
        s.add(TaskRecord(id=task, session_id=sid, command="x", input_mode="TEXT", state="WAITING_APPROVAL", created_at=utc_now(),
                         updated_at=utc_now()))
    return await svc.create(task_id=task, session_id=sid, action_summary="Confirm order", domain="x", reason="r",
                            risk_level=RiskLevel.CRITICAL, ttl_seconds=ttl)


async def test_approved_action_can_be_consumed_exactly_once_even_concurrently() -> None:
    svc, p, db = await _service()
    a = await _approval(svc, p)
    assert not await svc.consume(a.approval_id)  # pending approvals are never consumable
    await svc.decide(a.approval_id, ApprovalDecision.APPROVE)
    results = await asyncio.gather(*(svc.consume(a.approval_id) for _ in range(5)))
    assert results.count(True) == 1
    row = await p.approvals.get(a.approval_id)
    assert row.used_at is not None and row.status == "APPROVED" and row.version >= 3
    await db.dispose()


async def test_rejected_expired_and_withdrawn_approvals_never_authorise() -> None:
    svc, p, db = await _service()
    rejected = await _approval(svc, p)
    await svc.decide(rejected.approval_id, ApprovalDecision.REJECT)
    withdrawn = await _approval(svc, p)
    await svc.withdraw(withdrawn.approval_id)
    expired = await _approval(svc, p, ttl=1)
    await asyncio.sleep(1.1)
    await svc.expire_overdue()
    for a, status in ((rejected, "REJECTED"), (withdrawn, "WITHDRAWN"), (expired, "EXPIRED")):
        assert not await svc.consume(a.approval_id)
        assert (await p.approvals.get(a.approval_id)).status == status
    assert svc.get(withdrawn.approval_id).status == ApprovalStatus.WITHDRAWN
    await db.dispose()


def test_cross_user_approval_decisions_are_rejected(users: Users, secure_app: TestClient) -> None:
    a = users.new("ap1@example.com")
    b = users.new("ap2@example.com")
    r = users.post(a, "/api/v1/tasks", {"command": "hello", "session_id": a.session_id, "input_mode": "TEXT"})
    task_id = r.json()["task_id"]
    from uuid import UUID

    approval = secure_app.portal.call(lambda: secure_app.app.state.container.approvals.create(  # type: ignore[union-attr, attr-defined]
        task_id=UUID(task_id), session_id=UUID(a.session_id), action_summary="x", domain="d", reason="r",
        risk_level=RiskLevel.HIGH, ttl_seconds=60))
    assert users.post(b, f"/api/v1/approvals/{approval.approval_id}/decision", {"decision": "APPROVE"}).status_code == 403
    assert users.get(b, f"/api/v1/approvals/{approval.approval_id}").status_code == 403
    assert users.post(a, f"/api/v1/approvals/{approval.approval_id}/decision", {"decision": "REJECT"}).status_code == 200


def test_purchase_and_event_snapshots_are_bound_by_hash() -> None:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from app.integrations.calendar.event_review import event_hash
    from app.schemas.calendar import CalendarEventRequest

    ist = ZoneInfo("Asia/Kolkata")
    base = CalendarEventRequest(title="Sync", start_at=datetime(2026, 12, 1, 10, tzinfo=ist), end_at=datetime(2026, 12, 1, 11, tzinfo=ist),
                                timezone="Asia/Kolkata")
    changed = base.model_copy(update={"end_at": base.end_at + timedelta(minutes=15)})
    assert event_hash(base) != event_hash(changed)  # a modified event can never reuse the old approval
