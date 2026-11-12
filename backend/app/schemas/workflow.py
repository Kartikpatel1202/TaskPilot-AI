"""Multi-domain workflow state (Phase 5). Mirrors `frontend/src/types/workflow.ts`."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.calendar import CalendarEventReview
from app.schemas.files import DownloadAttempt
from app.schemas.gmail import EmailDraftSummary
from app.schemas.integration import DomainType, IntegrationCapability, PendingChoice
from app.schemas.youtube import YouTubePlayback, YouTubeVideo


class WorkflowStepStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    WAITING_USER = "WAITING_USER"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


class WorkflowStatus(str, Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    WAITING_USER = "WAITING_USER"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WorkflowStep(BaseModel):
    step_id: UUID
    order: int
    domain: DomainType
    capability: IntegrationCapability
    label: str
    status: WorkflowStepStatus = WorkflowStepStatus.NOT_STARTED
    depends_on: list[UUID] = Field(default_factory=list)
    message: str | None = None
    error_code: str | None = None
    produces: list[str] = Field(default_factory=list)
    consumes: list[str] = Field(default_factory=list)


class WorkflowOutput(BaseModel):
    """A typed, observed result handed to later steps (never pages, cookies or HTML)."""

    type: str  # youtube.video_reference | file.reference | gmail.draft_reference | calendar.event_reference
    step_id: UUID
    data: dict[str, str]


class WorkflowState(BaseModel):
    workflow_id: UUID
    task_id: UUID
    session_id: UUID
    domains: list[DomainType]
    steps: list[WorkflowStep]
    outputs: list[WorkflowOutput] = Field(default_factory=list)
    status: WorkflowStatus = WorkflowStatus.PLANNED
    current_domain: DomainType | None = None
    pending_choice: PendingChoice | None = None
    pending_approval_id: UUID | None = None
    final_result: str | None = None
    # Domain details (observed)
    youtube_results: list[YouTubeVideo] = Field(default_factory=list)
    youtube_selected: YouTubeVideo | None = None
    youtube_playback: YouTubePlayback | None = None
    gmail_draft: EmailDraftSummary | None = None
    calendar: CalendarEventReview | None = None
    downloads: list[DownloadAttempt] = Field(default_factory=list)
    updated_at: datetime
