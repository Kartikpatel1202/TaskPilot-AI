"""Task plan schemas. Mirrors `frontend/src/types/plan.ts`."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.action import DraftAction, SupportedAction
from app.schemas.approval import RiskLevel
from app.schemas.intent import IntentType, Language

PLAN_SCHEMA_VERSION = "1.0"


class PlanStatus(str, Enum):
    READY = "READY"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class PlannedAction(BaseModel):
    step_id: UUID
    order: int = Field(ge=1)
    action: SupportedAction
    description: str = Field(min_length=1, max_length=300)
    expected_outcome: str = Field(min_length=1, max_length=300)
    risk_level: RiskLevel
    requires_approval: bool = False
    depends_on: list[UUID] = Field(default_factory=list)


class ClarificationExchange(BaseModel):
    question: str
    answer: str
    answered_at: datetime


class TaskPlan(BaseModel):
    plan_id: UUID
    task_id: UUID
    session_id: UUID

    status: PlanStatus
    intent: IntentType

    summary: str
    user_facing_message: str
    language: Language = "en"
    target_website: str | None = None

    confidence: float = Field(ge=0, le=1)
    assumptions: list[str] = Field(default_factory=list)

    clarification_question: str | None = None
    missing_information: list[str] = Field(default_factory=list)
    clarification_history: list[ClarificationExchange] = Field(default_factory=list)

    steps: list[PlannedAction] = Field(default_factory=list)
    requires_human_approval: bool = False

    provider: str
    model: str
    is_mock: bool = False

    created_at: datetime
    schema_version: str = PLAN_SCHEMA_VERSION


# ---------------------------------------------------------------------- LLM response schema


class PlanStepDraft(BaseModel):
    order: int = Field(ge=1, le=100)
    action: DraftAction
    description: str = Field(min_length=1, max_length=300)
    expected_outcome: str = Field(min_length=1, max_length=300)
    risk_level: RiskLevel
    requires_approval: bool = False
    depends_on_orders: list[int] = Field(default_factory=list, max_length=10)


class PlanDraft(BaseModel):
    """What the LLM returns. Converted, risk-checked and validated by trusted code."""

    status: Literal["READY", "NEEDS_CLARIFICATION", "REJECTED"]
    summary: str = Field(min_length=1, max_length=300)
    user_facing_message: str = Field(min_length=1, max_length=800)
    confidence: float = Field(ge=0, le=1)
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    clarification_question: str | None = Field(default=None, max_length=400)
    missing_information: list[str] = Field(default_factory=list, max_length=10)
    steps: list[PlanStepDraft] = Field(default_factory=list, max_length=60)
