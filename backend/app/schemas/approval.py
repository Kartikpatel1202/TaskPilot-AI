"""Human-in-the-loop approval schemas. Mirrors `frontend/src/types/approval.ts`."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.calendar import CalendarApprovalDetails
from app.schemas.purchase import PurchaseApprovalDetails


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"  # Phase 6: the run was stopped/cancelled or recovered after a restart


class ApprovalDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ApprovalRequest(BaseModel):
    approval_id: UUID
    task_id: UUID
    session_id: UUID
    action_summary: str = Field(min_length=1, max_length=500)
    domain: str = Field(min_length=1, max_length=253)
    reason: str = Field(min_length=1, max_length=1000)
    risk_level: RiskLevel
    status: ApprovalStatus
    estimated_impact: str | None = Field(default=None, max_length=1000)
    expires_at: datetime
    is_demo: bool
    created_at: datetime
    resolved_at: datetime | None = None
    decision: ApprovalDecision | None = None
    # Phase 4: exact-order purchase review this approval is bound to (null for ordinary approvals).
    purchase: PurchaseApprovalDetails | None = None
    # Phase 5: the exact calendar event this approval is bound to (null otherwise).
    calendar: CalendarApprovalDetails | None = None


class CreateApprovalDecisionRequest(BaseModel):
    decision: ApprovalDecision


class ApprovalResponse(BaseModel):
    approval_id: UUID
    decision: ApprovalDecision
    status: ApprovalStatus
    resolved_at: datetime


class DemoRequest(BaseModel):
    """Body for development-only demo endpoints."""

    session_id: UUID


class DemoAcceptedResponse(BaseModel):
    accepted: bool
    message: str
    task_id: UUID
    is_demo: bool = True
