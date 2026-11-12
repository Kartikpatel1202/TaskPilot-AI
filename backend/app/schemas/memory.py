"""Session conversation memory schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.intent import IntentType, ProductEntity


class ConversationRole(str, Enum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    SYSTEM = "SYSTEM"


class ConversationTurn(BaseModel):
    turn_id: UUID
    session_id: UUID
    task_id: UUID | None
    role: ConversationRole
    content: str
    intent: IntentType | None = None
    created_at: datetime


class SessionContext(BaseModel):
    """Structured task context carried between turns of one session."""

    active_website: str | None = None
    active_intent: IntentType | None = None
    products: list[ProductEntity] = Field(default_factory=list)
    last_task_id: UUID | None = None


class ContextTurn(BaseModel):
    role: ConversationRole
    content: str
    intent: IntentType | None = None


class PlanningContext(BaseModel):
    """What the planner sees about the past — bounded and redacted."""

    summary: str | None = None
    recent_turns: list[ContextTurn] = Field(default_factory=list)
    session_context: SessionContext = Field(default_factory=SessionContext)
    # Settings-page profile shown to the model: preferred name and reply language only (no secrets).
    user_profile: dict[str, str] = Field(default_factory=dict)
