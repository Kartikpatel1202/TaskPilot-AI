"""Workflow state snapshots (observed results only)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.database.models import WorkflowRecord
from app.database.session import Database
from app.schemas.workflow import WorkflowState


class WorkflowRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def save(self, state: WorkflowState, *, user_id: UUID | None = None) -> None:
        data = state.model_dump(mode="json")
        async with self.db.session() as s:
            row = await s.scalar(select(WorkflowRecord).where(WorkflowRecord.task_id == state.task_id))
            if row is None:
                s.add(WorkflowRecord(id=state.workflow_id, task_id=state.task_id, user_id=user_id, domains=[d.value for d in state.domains],
                                     status=state.status.value, state_json=data, updated_at=state.updated_at))
            else:
                row.status, row.state_json, row.updated_at = state.status.value, data, state.updated_at

    async def get(self, task_id: UUID) -> WorkflowState | None:
        async with self.db.session() as s:
            row = await s.scalar(select(WorkflowRecord).where(WorkflowRecord.task_id == task_id))
        return WorkflowState.model_validate(row.state_json) if row else None
