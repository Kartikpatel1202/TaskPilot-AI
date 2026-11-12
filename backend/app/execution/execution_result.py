"""Execution results. Every status here comes from observed browser behaviour."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ActionExecutionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


class ExecutionStatus(str, Enum):
    QUEUED = "QUEUED"
    EXECUTING = "EXECUTING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ActionResult(BaseModel):
    step_id: UUID
    order: int = 0
    action_type: str = ""
    status: ActionExecutionStatus
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    message: str
    error_code: str | None = None
    extracted_data: dict[str, Any] | None = None
    retry_count: int = 0
    # True when a visible outcome (navigation, DOM change, input value) was observed.
    verified: bool = False
    strategy: str | None = None
    confidence: float | None = None


class ExecutionSummary(BaseModel):
    task_id: UUID
    session_id: UUID
    plan_id: UUID
    status: ExecutionStatus
    total_steps: int
    results: list[ActionResult] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    message: str | None = None
    error_code: str | None = None

    def count(self, status: ActionExecutionStatus) -> int:
        return sum(1 for r in self.results if r.status == status)
