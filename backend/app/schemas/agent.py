"""Agent-level API schemas. Mirrors `frontend/src/types/agent.ts`."""

from __future__ import annotations

from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.schemas.task import InputMode, TaskState


class PlanningStage(str, Enum):
    UNDERSTANDING_COMMAND = "UNDERSTANDING_COMMAND"
    CLASSIFYING_INTENT = "CLASSIFYING_INTENT"
    BUILDING_PLAN = "BUILDING_PLAN"
    VALIDATING_PLAN = "VALIDATING_PLAN"
    FINALIZING = "FINALIZING"


# Progress is derived from the stage position, never invented.
STAGE_ORDER: tuple[PlanningStage, ...] = tuple(PlanningStage)


def stage_progress(stage: PlanningStage) -> int:
    return round((STAGE_ORDER.index(stage) + 1) / (len(STAGE_ORDER) + 1) * 100)


AgentAvailability = Literal["available", "disabled", "misconfigured", "unavailable"]


class AgentStatusResponse(BaseModel):
    agent_name: str
    provider: str
    model: str
    status: AgentAvailability
    planning_enabled: bool
    browser_execution_enabled: bool
    is_mock: bool
    provider_reachable: bool | None = None
    # 'ai' when a real LLM plans; 'offline_rules' for the deterministic offline planner.
    planner_kind: str = "ai"
    setup_hint: str | None = None


class ClarificationRequest(BaseModel):
    session_id: UUID
    message: str = Field(min_length=1, max_length=4000)
    input_mode: InputMode = InputMode.TEXT

    @field_validator("message")
    @classmethod
    def _validate_message(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Clarification must not be empty or whitespace only.")
        if len(stripped) > get_settings().max_command_length:
            raise ValueError("Clarification is too long.")
        return stripped


class ClarificationAcceptedResponse(BaseModel):
    task_id: UUID
    accepted: bool
    state: TaskState
    message: str
