"""Tasks: upsert on every state change; owner-scoped history with cursor pagination."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select

from app.core.logging import redact_text
from app.database.models import TaskRecord
from app.database.session import Database
from app.schemas.task import InputMode, Task, TaskState

ACTIVE_STATES = ("IDLE", "PLANNING", "PLANNED", "NEEDS_CLARIFICATION", "EXECUTING", "WAITING_APPROVAL")


def to_task(r: TaskRecord) -> Task:
    return Task(task_id=r.id, session_id=r.session_id, command=r.command, input_mode=InputMode(r.input_mode), state=TaskState(r.state),
                created_at=r.created_at, updated_at=r.updated_at, is_demo=r.is_demo, error_message=r.error_message)


class TaskRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def upsert(self, task: Task, *, user_id: UUID | None = None, error_code: str | None = None,
                     execution_status: str | None = None, recovery_note: str | None = None) -> None:
        async with self.db.session() as s:
            row = await s.get(TaskRecord, task.task_id)
            if row is None:
                row = TaskRecord(id=task.task_id, user_id=user_id, session_id=task.session_id, command=redact_text(task.command)[:4000],
                                 input_mode=task.input_mode.value, state=task.state.value, is_demo=task.is_demo,
                                 created_at=task.created_at, updated_at=task.updated_at)
                s.add(row)
            row.state = task.state.value
            row.updated_at = task.updated_at
            row.error_message = (task.error_message or None) and task.error_message[:1000]
            if user_id is not None and row.user_id is None:
                row.user_id = user_id
            if error_code is not None:
                row.error_code = error_code[:80]
            if execution_status is not None:
                row.execution_status = execution_status[:32]
            if recovery_note is not None:
                row.recovery_note = recovery_note[:1000]

    async def get(self, task_id: UUID) -> TaskRecord | None:
        async with self.db.session() as s:
            return await s.get(TaskRecord, task_id)

    async def owner_of(self, task_id: UUID) -> tuple[UUID | None, UUID] | None:
        row = await self.get(task_id)
        return (row.user_id, row.session_id) if row else None

    async def active(self, limit: int = 1000) -> list[TaskRecord]:
        async with self.db.session() as s:
            rows = await s.scalars(select(TaskRecord).where(TaskRecord.state.in_(ACTIVE_STATES)).order_by(TaskRecord.created_at).limit(limit))
            return list(rows)

    async def history(self, *, user_id: UUID | None, session_ids: list[UUID] | None, limit: int,
                      before: tuple[datetime, UUID] | None = None, state: str | None = None) -> list[TaskRecord]:
        """Newest first; keyset pagination on (created_at, id). Scoped to the user (or explicit sessions in dev mode)."""
        conds = []
        if user_id is not None:
            conds.append(TaskRecord.user_id == user_id)
        elif session_ids is not None:
            conds.append(TaskRecord.session_id.in_(session_ids))
        else:
            return []
        if state:
            conds.append(TaskRecord.state == state)
        if before is not None:
            created, tid = before
            conds.append(or_(TaskRecord.created_at < created, and_(TaskRecord.created_at == created, TaskRecord.id < tid)))
        async with self.db.session() as s:
            rows = await s.scalars(select(TaskRecord).where(*conds).order_by(TaskRecord.created_at.desc(), TaskRecord.id.desc()).limit(limit))
            return list(rows)
