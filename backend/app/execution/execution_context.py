"""Per-execution context handed to action handlers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.execution.execution_result import ActionExecutionStatus, ActionResult
from app.schemas.common import utc_now
from app.schemas.plan import PlannedAction, TaskPlan

if TYPE_CHECKING:
    from app.browser.controller import BrowserController
    from app.core.execution_events import ExecutionEvents
    from app.execution.approval_coordinator import ApprovalCoordinator
    from app.policies.browser_action_policy import BrowserActionPolicy
    from app.services.task_service import TaskService


@dataclass
class ExecutionContext:
    task_id: UUID
    session_id: UUID
    plan: TaskPlan
    controller: BrowserController
    policy: BrowserActionPolicy
    telemetry: ExecutionEvents
    approvals: ApprovalCoordinator
    tasks: TaskService
    approval_ttl_seconds: int
    max_retries: int
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    results: dict[UUID, ActionResult] = field(default_factory=dict)
    current_step: PlannedAction | None = None
    next_step: PlannedAction | None = None
    step_started_at: datetime = field(default_factory=utc_now)
    cancel_reason: str | None = None
    announced_page: tuple[str | None, str | None] | None = None  # last page reported via page_updated
    commerce: Any = None  # Phase 4 CommerceManager (None when commerce is disabled)
    integrations: Any = None  # Phase 5 IntegrationManager (None when integrations are disabled)
    journal: Any = None  # Phase 6 ExecutionJournal (idempotency + recovery)
    recovery: Any = None  # Phase 6 RecoveryEngine (bounded selector self-correction)
    user_id: Any = None  # Phase 6 owner of the task (for quotas and rate limits)
    reconciling: bool = False  # Phase 6: the current step's earlier attempt was interrupted; inspect state first

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def result(
        self,
        status: ActionExecutionStatus,
        message: str,
        *,
        error_code: str | None = None,
        extracted_data: dict[str, Any] | None = None,
        verified: bool = False,
        strategy: str | None = None,
        confidence: float | None = None,
        retry_count: int = 0,
    ) -> ActionResult:
        step = self.current_step
        assert step is not None
        done = utc_now()
        return ActionResult(
            step_id=step.step_id,
            order=step.order,
            action_type=step.action.type,
            status=status,
            started_at=self.step_started_at,
            completed_at=done,
            duration_ms=int((done - self.step_started_at).total_seconds() * 1000),
            message=message,
            error_code=error_code,
            extracted_data=extracted_data,
            retry_count=retry_count,
            verified=verified,
            strategy=strategy,
            confidence=round(confidence, 3) if confidence is not None else None,
        )
