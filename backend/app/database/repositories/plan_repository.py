"""Plans: append each validated plan version; the newest one per task is current."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.logging import redact_text
from app.database.models import PlanRecord
from app.database.session import Database
from app.schemas.plan import PLAN_SCHEMA_VERSION, TaskPlan


class PlanRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def save(self, plan: TaskPlan, *, user_id: UUID | None, command: str | None, clarifications: list[dict[str, Any]]) -> None:
        async with self.db.session() as s:
            row = await s.get(PlanRecord, plan.plan_id)
            data = plan.model_dump(mode="json")
            if row is None:
                s.add(PlanRecord(id=plan.plan_id, task_id=plan.task_id, user_id=user_id, schema_version=PLAN_SCHEMA_VERSION,
                                 status=plan.status.value, provider=plan.provider, model=plan.model, plan_json=data,
                                 command=redact_text(command)[:4000] if command else None, clarifications_json=clarifications,
                                 created_at=plan.created_at))
            else:  # e.g. the user edited the planned draft before Run Plan
                row.plan_json = data
                row.status = plan.status.value

    async def latest(self, task_id: UUID) -> PlanRecord | None:
        async with self.db.session() as s:
            return await s.scalar(select(PlanRecord).where(PlanRecord.task_id == task_id).order_by(PlanRecord.created_at.desc()).limit(1))

    async def latest_plan(self, task_id: UUID) -> TaskPlan | None:
        row = await self.latest(task_id)
        return TaskPlan.model_validate(row.plan_json) if row else None
