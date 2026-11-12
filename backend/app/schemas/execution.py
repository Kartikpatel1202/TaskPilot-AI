"""Execution API + telemetry schemas (Phase 3). Mirrors `frontend/src/types/execution.ts`."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.execution.execution_result import ActionExecutionStatus, ActionResult, ExecutionStatus, ExecutionSummary

__all__ = [
    "ActionExecutionStatus",
    "ActionResult",
    "ExecutionStatus",
    "ExecutionSummary",
]


class ExecuteTaskRequest(BaseModel):
    session_id: UUID
    # Must be literally true: execution only ever starts from an explicit user action.
    confirm_execution: Literal[True]
    # run_plan_click: the user pressed Run Plan. voice_auto: the user spoke the request in voice mode with
    # "auto-run" enabled in Settings — accepted only for plans without HIGH/CRITICAL or approval-gated steps.
    trigger: Literal["run_plan_click", "voice_auto"] = "run_plan_click"


class ExecutionAcceptedResponse(BaseModel):
    task_id: UUID
    session_id: UUID
    status: Literal["ACCEPTED"] = "ACCEPTED"
    message: str


class StopTaskRequest(BaseModel):
    session_id: UUID
    reason: str = Field(default="User requested stop", min_length=1, max_length=200)


class StopTaskResponse(BaseModel):
    task_id: UUID
    status: Literal["STOPPING", "CANCELLED"]
    message: str


# ---------------------------------------------------------------------- telemetry payloads


class ExecutionStartedPayload(BaseModel):
    plan_id: UUID
    total_steps: int
    engine: str
    headless: bool


class StepStartedPayload(BaseModel):
    step_id: UUID
    order: int
    action_type: str
    description: str


class StepCompletedPayload(BaseModel):
    step_id: UUID
    order: int
    status: ActionExecutionStatus
    duration_ms: int | None
    message: str
    verified: bool = False
    extracted_data: dict[str, Any] | None = None


class StepFailedPayload(BaseModel):
    step_id: UUID
    order: int
    status: ActionExecutionStatus
    error_code: str
    message: str
    duration_ms: int | None = None


class ExecutionPausedPayload(BaseModel):
    step_id: UUID
    reason: str
    approval_id: UUID | None = None


class ExecutionResumedPayload(BaseModel):
    step_id: UUID
    message: str


class ExecutionFinishedPayload(BaseModel):
    status: ExecutionStatus
    total_steps: int
    succeeded_steps: int
    failed_steps: int
    blocked_steps: int
    skipped_steps: int
    message: str
    error_code: str | None = None
