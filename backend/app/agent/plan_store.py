"""Bounded in-memory storage of planning records (one per task)."""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field
from uuid import UUID

from app.agent.providers.base import LLMUsage
from app.schemas.plan import ClarificationExchange, TaskPlan


@dataclass
class PlanningRecord:
    task_id: UUID
    session_id: UUID
    command: str
    clarifications: list[ClarificationExchange] = field(default_factory=list)
    pending_question: str | None = None
    plan: TaskPlan | None = None
    previous_plans: deque[TaskPlan] = field(default_factory=lambda: deque(maxlen=5))
    # Provider usage is kept server-side only (never part of the user-visible plan).
    usage: list[LLMUsage] = field(default_factory=list)
    user_turn_recorded: bool = False
    # Settings profile for this task (preferred name and language), loaded when planning starts.
    profile: dict[str, str] = field(default_factory=dict)

    def set_plan(self, plan: TaskPlan) -> None:
        if self.plan is not None:
            self.previous_plans.append(self.plan)
        self.plan = plan


class PlanStore:
    def __init__(self, max_records: int) -> None:
        self._max = max_records
        self._records: OrderedDict[UUID, PlanningRecord] = OrderedDict()

    def create(self, task_id: UUID, session_id: UUID, command: str) -> PlanningRecord:
        record = PlanningRecord(task_id=task_id, session_id=session_id, command=command)
        self._records[task_id] = record
        while len(self._records) > self._max:
            self._records.popitem(last=False)
        return record

    def get(self, task_id: UUID) -> PlanningRecord | None:
        return self._records.get(task_id)
