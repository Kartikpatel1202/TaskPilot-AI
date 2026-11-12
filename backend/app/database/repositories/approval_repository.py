"""Approvals: optimistic state transitions and atomic one-time consumption."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update

from app.database.models import ApprovalRecord
from app.database.session import Database
from app.schemas.approval import ApprovalRequest
from app.schemas.common import utc_now


def _kind(a: ApprovalRequest) -> tuple[str, str | None]:
    if a.purchase is not None:
        return "purchase", a.purchase.summary_hash
    if a.calendar is not None:
        return "calendar", a.calendar.event_hash
    return "generic", None


class ApprovalRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def save(self, a: ApprovalRequest, *, user_id: UUID | None = None) -> None:
        kind, snapshot = _kind(a)
        async with self.db.session() as s:
            row = await s.get(ApprovalRecord, a.approval_id)
            if row is None:
                s.add(ApprovalRecord(id=a.approval_id, task_id=a.task_id, user_id=user_id, session_id=a.session_id, action_type=kind,
                                     snapshot_hash=snapshot, status=a.status.value, risk_level=a.risk_level.value, is_demo=a.is_demo,
                                     request_json=a.model_dump(mode="json"), created_at=a.created_at, expires_at=a.expires_at))
                return
            row.status = a.status.value
            row.resolved_at = a.resolved_at
            row.decision = a.decision.value if a.decision else None
            row.request_json = a.model_dump(mode="json")
            row.version += 1

    async def get(self, approval_id: UUID) -> ApprovalRecord | None:
        async with self.db.session() as s:
            return await s.get(ApprovalRecord, approval_id)

    async def consume(self, approval_id: UUID) -> bool:
        """Mark an APPROVED approval as used — succeeds exactly once (atomic conditional UPDATE)."""
        async with self.db.session() as s:
            result = await s.execute(update(ApprovalRecord).where(
                ApprovalRecord.id == approval_id, ApprovalRecord.status == "APPROVED", ApprovalRecord.used_at.is_(None),
            ).values(used_at=utc_now(), version=ApprovalRecord.version + 1))
            return (result.rowcount or 0) == 1

    async def pending(self) -> list[ApprovalRecord]:
        async with self.db.session() as s:
            return list(await s.scalars(select(ApprovalRecord).where(ApprovalRecord.status == "PENDING")))
