"""Telemetry (WebSocket) schemas. Mirrors `frontend/src/types/telemetry.ts`."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Union
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter

from app.schemas.approval import ApprovalDecision, ApprovalStatus
from app.schemas.task import InputMode, TaskState


class TelemetryEventType(str, Enum):
    CONNECTION_READY = "connection.ready"
    TASK_ACCEPTED = "task.accepted"
    TASK_STATE_CHANGED = "task.state_changed"
    LOG_CREATED = "log.created"
    BROWSER_PREVIEW = "browser.preview"
    APPROVAL_REQUIRED = "approval.required"
    APPROVAL_RESOLVED = "approval.resolved"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    SYSTEM_ERROR = "system.error"
    # Phase 2 — agent planning
    AGENT_INTENT_DETECTED = "agent.intent_detected"
    AGENT_PLANNING_STARTED = "agent.planning_started"
    AGENT_PLANNING_PROGRESS = "agent.planning_progress"
    TASK_PLAN_READY = "task.plan_ready"
    TASK_CLARIFICATION_REQUIRED = "task.clarification_required"
    TASK_PLANNING_FAILED = "task.planning_failed"
    AGENT_RESPONSE_GENERATED = "agent.response_generated"
    # Phase 3 — browser
    BROWSER_SESSION_STARTED = "browser.session_started"
    BROWSER_SESSION_READY = "browser.session_ready"
    BROWSER_NAVIGATION_STARTED = "browser.navigation_started"
    BROWSER_NAVIGATION_COMPLETED = "browser.navigation_completed"
    BROWSER_NAVIGATION_BLOCKED = "browser.navigation_blocked"
    BROWSER_PAGE_UPDATED = "browser.page_updated"
    BROWSER_FRAME_AVAILABLE = "browser.frame_available"
    BROWSER_ACTION_STARTED = "browser.action_started"
    BROWSER_ACTION_COMPLETED = "browser.action_completed"
    BROWSER_ACTION_FAILED = "browser.action_failed"
    BROWSER_AUTHENTICATION_REQUIRED = "browser.authentication_required"
    BROWSER_POPUP_BLOCKED = "browser.popup_blocked"
    BROWSER_DOWNLOAD_BLOCKED = "browser.download_blocked"
    BROWSER_SESSION_CLOSED = "browser.session_closed"
    BROWSER_SESSION_ERROR = "browser.session_error"
    BROWSER_STREAM_CONNECTED = "browser.stream_connected"
    BROWSER_STREAM_DISCONNECTED = "browser.stream_disconnected"
    # Phase 3 — execution
    TASK_EXECUTION_STARTED = "task.execution_started"
    TASK_STEP_STARTED = "task.step_started"
    TASK_STEP_COMPLETED = "task.step_completed"
    TASK_STEP_FAILED = "task.step_failed"
    TASK_STEP_BLOCKED = "task.step_blocked"
    TASK_EXECUTION_PAUSED = "task.execution_paused"
    TASK_EXECUTION_RESUMED = "task.execution_resumed"
    TASK_EXECUTION_COMPLETED = "task.execution_completed"
    TASK_EXECUTION_FAILED = "task.execution_failed"
    TASK_EXECUTION_CANCELLED = "task.execution_cancelled"
    # Phase 4 — commerce
    COMMERCE_SESSION_DETECTED = "commerce.session_detected"
    COMMERCE_LOCATION_REQUIRED = "commerce.location_required"
    COMMERCE_SEARCH_STARTED = "commerce.search_started"
    COMMERCE_SEARCH_COMPLETED = "commerce.search_completed"
    COMMERCE_PRODUCTS_FOUND = "commerce.products_found"
    COMMERCE_PRODUCT_SELECTED = "commerce.product_selected"
    COMMERCE_PRODUCT_AMBIGUOUS = "commerce.product_ambiguous"
    COMMERCE_PRODUCT_UNAVAILABLE = "commerce.product_unavailable"
    COMMERCE_CART_UPDATE_STARTED = "commerce.cart_update_started"
    COMMERCE_CART_ITEM_ADDED = "commerce.cart_item_added"
    COMMERCE_CART_ITEM_UPDATED = "commerce.cart_item_updated"
    COMMERCE_CART_VERIFICATION_STARTED = "commerce.cart_verification_started"
    COMMERCE_CART_VERIFICATION_COMPLETED = "commerce.cart_verification_completed"
    COMMERCE_CART_VERIFICATION_FAILED = "commerce.cart_verification_failed"
    COMMERCE_PRICE_CHANGED = "commerce.price_changed"
    COMMERCE_CHECKOUT_REVIEW_READY = "commerce.checkout_review_ready"
    COMMERCE_PURCHASE_APPROVAL_REQUIRED = "commerce.purchase_approval_required"
    COMMERCE_PURCHASE_REJECTED = "commerce.purchase_rejected"
    COMMERCE_PAYMENT_HANDOFF = "commerce.payment_handoff"
    COMMERCE_ORDER_SUBMISSION_STARTED = "commerce.order_submission_started"
    COMMERCE_ORDER_CONFIRMED = "commerce.order_confirmed"
    COMMERCE_ORDER_STATUS_UNKNOWN = "commerce.order_status_unknown"
    COMMERCE_WORKFLOW_FAILED = "commerce.workflow_failed"
    # Phase 5 — multi-domain integrations
    INTEGRATION_DOMAIN_SELECTED = "integration.domain_selected"
    INTEGRATION_CAPABILITY_SELECTED = "integration.capability_selected"
    INTEGRATION_AUTHENTICATION_REQUIRED = "integration.authentication_required"
    INTEGRATION_SESSION_READY = "integration.session_ready"
    INTEGRATION_ERROR = "integration.error"
    YOUTUBE_SEARCH_STARTED = "youtube.search_started"
    YOUTUBE_SEARCH_COMPLETED = "youtube.search_completed"
    YOUTUBE_RESULTS_FOUND = "youtube.results_found"
    YOUTUBE_VIDEO_SELECTED = "youtube.video_selected"
    YOUTUBE_PLAYBACK_STARTED = "youtube.playback_started"
    YOUTUBE_PLAYBACK_PAUSED = "youtube.playback_paused"
    YOUTUBE_PLAYBACK_ERROR = "youtube.playback_error"
    GMAIL_DRAFT_STARTED = "gmail.draft_started"
    GMAIL_DRAFT_COMPOSED = "gmail.draft_composed"
    GMAIL_DRAFT_SAVED = "gmail.draft_saved"
    GMAIL_DRAFT_VERIFIED = "gmail.draft_verified"
    GMAIL_DRAFT_FAILED = "gmail.draft_failed"
    GMAIL_SEND_BLOCKED = "gmail.send_blocked"
    CALENDAR_EVENT_PREPARED = "calendar.event_prepared"
    CALENDAR_CONFLICT_DETECTED = "calendar.conflict_detected"
    CALENDAR_APPROVAL_REQUIRED = "calendar.approval_required"
    CALENDAR_APPROVAL_RESOLVED = "calendar.approval_resolved"
    CALENDAR_EVENT_CREATION_STARTED = "calendar.event_creation_started"
    CALENDAR_EVENT_CREATED = "calendar.event_created"
    CALENDAR_EVENT_CREATION_FAILED = "calendar.event_creation_failed"
    FILE_DOWNLOAD_STARTED = "file.download_started"
    FILE_DOWNLOAD_PROGRESS = "file.download_progress"
    FILE_DOWNLOAD_COMPLETED = "file.download_completed"
    FILE_DOWNLOAD_BLOCKED = "file.download_blocked"
    FILE_DOWNLOAD_FAILED = "file.download_failed"
    FILE_VALIDATION_COMPLETED = "file.validation_completed"
    WORKFLOW_STEP_STARTED = "workflow.step_started"
    WORKFLOW_STEP_COMPLETED = "workflow.step_completed"
    WORKFLOW_STEP_FAILED = "workflow.step_failed"
    WORKFLOW_PARTIAL_SUCCESS = "workflow.partial_success"
    WORKFLOW_COMPLETED = "workflow.completed"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    SUCCESS = "SUCCESS"


LogSource = Literal["system", "assistant", "demo"]
Language = Literal["en", "hi", "hinglish"]


class TelemetryEvent(BaseModel):
    """Server-to-client event envelope."""

    event_id: UUID
    session_id: UUID
    task_id: UUID | None
    sequence: int = Field(ge=1)
    type: TelemetryEventType
    occurred_at: datetime
    data: dict[str, Any]


# --------------------------------------------------------------------------- payloads


class ConnectionReadyPayload(BaseModel):
    connection_id: UUID
    server_version: str
    assistant_name: str
    heartbeat_interval_seconds: int
    history_limit: int
    demo_endpoints_enabled: bool


class TaskAcceptedPayload(BaseModel):
    task_id: UUID
    state: TaskState
    command: str
    input_mode: InputMode
    created_at: datetime
    is_demo: bool = False


class TaskStateChangedPayload(BaseModel):
    previous_state: TaskState
    new_state: TaskState
    reason: str | None = None
    is_demo: bool = False


class LogPayload(BaseModel):
    level: LogLevel
    message: str = Field(max_length=2000)
    source: LogSource = "system"
    language: Language | None = None
    metadata: dict[str, Any] | None = None
    is_demo: bool = False


class BrowserPreviewMode(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    PLACEHOLDER = "PLACEHOLDER"
    # Reserved for Phase 3 (real Playwright frames). Never emitted in Phase 1.
    FRAME = "FRAME"


class BrowserPreviewPayload(BaseModel):
    mode: BrowserPreviewMode
    message: str
    url: str | None = None
    frame_data_url: str | None = None
    is_demo: bool = False


class ApprovalResolvedPayload(BaseModel):
    approval_id: UUID
    decision: ApprovalDecision | None
    status: ApprovalStatus
    resolved_at: datetime
    is_demo: bool = False


class TaskCompletedPayload(BaseModel):
    summary: str
    is_demo: bool = False


class TaskFailedPayload(BaseModel):
    error_code: str
    error_message: str
    is_demo: bool = False


class SystemErrorPayload(BaseModel):
    code: str
    message: str


# --------------------------------------------------------------------------- Phase 2 payloads


class IntentDetectedPayload(BaseModel):
    intent: str
    confidence: float
    target_website: str | None = None
    language: Language = "en"
    requires_clarification: bool = False
    is_follow_up: bool = False


class PlanningStartedPayload(BaseModel):
    status: TaskState = TaskState.PLANNING
    message: str
    is_clarification: bool = False


class PlanningProgressPayload(BaseModel):
    stage: str
    progress: int = Field(ge=0, le=100)
    message: str


class PlanReadyPayload(BaseModel):
    plan_id: UUID
    status: str
    intent: str
    summary: str
    step_count: int
    requires_human_approval: bool
    provider: str
    model: str
    is_mock: bool


class ClarificationRequiredPayload(BaseModel):
    plan_id: UUID
    question: str
    missing_information: list[str] = Field(default_factory=list)


class PlanningFailedPayload(BaseModel):
    code: str
    message: str
    retryable: bool = False


AgentResponseKind = Literal["acknowledgement", "plan_ready", "clarification", "rejected", "failed", "chat", "execution"]


class AgentResponsePayload(BaseModel):
    message: str = Field(max_length=2000)
    language: Language = "en"
    kind: AgentResponseKind


# --------------------------------------------------------------------------- client messages


class SubscribeMessage(BaseModel):
    type: Literal["subscribe"]
    after_event_id: UUID | None = None


class PingMessage(BaseModel):
    type: Literal["ping"]


ClientMessage = Annotated[Union[SubscribeMessage, PingMessage], Field(discriminator="type")]
client_message_adapter: TypeAdapter[SubscribeMessage | PingMessage] = TypeAdapter(ClientMessage)
