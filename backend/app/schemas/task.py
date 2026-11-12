"""Task schemas. Field names are kept identical to `frontend/src/types/task.ts`."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.config import get_settings


class TaskState(str, Enum):
    IDLE = "IDLE"
    PLANNING = "PLANNING"
    PLANNED = "PLANNED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    EXECUTING = "EXECUTING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class InputMode(str, Enum):
    TEXT = "TEXT"
    VOICE = "VOICE"


class CreateTaskRequest(BaseModel):
    command: str = Field(min_length=1, max_length=4000)
    session_id: UUID
    input_mode: InputMode

    @field_validator("command")
    @classmethod
    def _validate_command(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Command must not be empty or whitespace only.")
        limit = get_settings().max_command_length
        if len(stripped) > limit:
            raise ValueError(f"Command must be at most {limit} characters.")
        return stripped


class Task(BaseModel):
    """In-memory task record (no persistence in Phase 1)."""

    task_id: UUID
    session_id: UUID
    command: str
    input_mode: InputMode
    state: TaskState
    created_at: datetime
    updated_at: datetime
    error_message: str | None = None
    is_demo: bool = False


class TaskAcceptedResponse(BaseModel):
    task_id: UUID
    session_id: UUID
    state: TaskState
    accepted: bool
    message: str
    created_at: datetime


class TaskListResponse(BaseModel):
    tasks: list[Task]
