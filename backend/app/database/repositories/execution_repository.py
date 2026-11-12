"""Execution journal with idempotency keys (unique) and safe lifecycle transitions."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.database.models import ActionJournalRecord, ActionLifecycle
from app.database.session import Database
from app.schemas.common import utc_now

TERMINAL = {ActionLifecycle.SUCCEEDED.value, ActionLifecycle.FAILED.value, ActionLifecycle.BLOCKED.value, ActionLifecycle.CANCELLED.value}


def idempotency_key(task_id: UUID, plan_id: UUID, step_id: UUID, version: int = 1) -> str:
    return f"{task_id}:{plan_id}:{step_id}:v{version}"


class ExecutionRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def get(self, key: str) -> ActionJournalRecord | None:
        async with self.db.session() as s:
            return await s.scalar(select(ActionJournalRecord).where(ActionJournalRecord.idempotency_key == key))

    async def prepare(self, *, key: str, task_id: UUID, plan_id: UUID, step_id: UUID, order: int, action_type: str, mutating: bool,
                      worker_id: str | None) -> tuple[ActionJournalRecord, bool]:
        """Create the PREPARED row; (row, created). An existing row means this action was attempted before."""
        now = utc_now()
        try:
            async with self.db.session() as s:
                row = ActionJournalRecord(idempotency_key=key, task_id=task_id, plan_id=plan_id, step_id=step_id, step_order=order,
                                          action_type=action_type, mutating=mutating, lifecycle=ActionLifecycle.PREPARED.value,
                                          worker_id=worker_id, created_at=now)
                s.add(row)
            return row, True
        except IntegrityError:
            existing = await self.get(key)
            assert existing is not None
            return existing, False

    async def mark(self, key: str, lifecycle: ActionLifecycle, *, error_code: str | None = None, result: dict[str, Any] | None = None,
                   bump_attempt: bool = False) -> None:
        now = utc_now()
        async with self.db.session() as s:
            row = await s.scalar(select(ActionJournalRecord).where(ActionJournalRecord.idempotency_key == key))
            if row is None:
                return
            row.lifecycle = lifecycle.value
            if lifecycle == ActionLifecycle.RUNNING:
                row.started_at = now
                if bump_attempt:
                    row.attempt += 1
            if lifecycle.value in TERMINAL or lifecycle == ActionLifecycle.UNKNOWN:
                row.completed_at = now
                if row.started_at is not None:
                    row.duration_ms = int((now - row.started_at).total_seconds() * 1000)
            if error_code is not None:
                row.error_code = error_code[:80]
            if result is not None:
                row.result_json = result

    async def for_task(self, task_id: UUID) -> list[ActionJournalRecord]:
        async with self.db.session() as s:
            rows = await s.scalars(select(ActionJournalRecord).where(ActionJournalRecord.task_id == task_id).order_by(ActionJournalRecord.step_order))
            return list(rows)

    async def mark_in_flight_unknown(self, task_id: UUID) -> list[ActionJournalRecord]:
        """After a crash: RUNNING mutations -> UNKNOWN (never assumed done or not done); PREPARED -> CANCELLED."""
        rows = await self.for_task(task_id)
        changed = []
        async with self.db.session() as s:
            for row in rows:
                if row.lifecycle == ActionLifecycle.RUNNING.value:
                    new = ActionLifecycle.UNKNOWN if row.mutating else ActionLifecycle.FAILED
                elif row.lifecycle == ActionLifecycle.PREPARED.value:
                    new = ActionLifecycle.CANCELLED
                else:
                    continue
                await s.execute(update(ActionJournalRecord).where(ActionJournalRecord.id == row.id).values(
                    lifecycle=new.value, completed_at=utc_now(), error_code="EXECUTION_INTERRUPTED"))
                row.lifecycle = new.value
                changed.append(row)
        return changed
