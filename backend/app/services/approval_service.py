"""Human-in-the-loop approval service (in-memory, Phase 1).

Decisions are immutable, only PENDING approvals can be decided, and expired
approvals cannot be approved. Resolving an approval NEVER triggers a
real-world action in Phase 1 — it only records the decision and publishes
`approval.resolved`. Optional resolution handlers let other modules (e.g. the
dev simulation) react to decisions without coupling.
"""

from __future__ import annotations

from typing import Any

import asyncio
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Awaitable, Callable
from uuid import UUID, uuid4

from app.core.event_manager import EventManager
from app.core.logging import get_logger
from app.schemas.calendar import CalendarApprovalDetails
from app.schemas.purchase import PurchaseApprovalDetails
from app.schemas.approval import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalStatus,
    RiskLevel,
)
from app.schemas.common import utc_now
from app.schemas.telemetry import ApprovalResolvedPayload, TelemetryEventType

logger = get_logger("approvals")

ResolutionHandler = Callable[[ApprovalRequest], Awaitable[None]]


class ApprovalNotFoundError(LookupError):
    pass


class ApprovalAlreadyResolvedError(RuntimeError):
    def __init__(self, status: ApprovalStatus) -> None:
        self.status = status
        super().__init__(f"Approval already resolved with status {status.value}.")


class ApprovalExpiredError(RuntimeError):
    pass


class ApprovalService:
    def __init__(
        self,
        events: EventManager,
        max_items: int = 1000,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._events = events
        self._max_items = max_items
        self._clock = clock
        self._approvals: OrderedDict[UUID, ApprovalRequest] = OrderedDict()
        self._lock = asyncio.Lock()
        self._handlers: list[ResolutionHandler] = []
        self.persistence: Any = None  # Phase 6 Persistence (set by the container)
        self.owner_lookup: Any = None
        self._consumed: set[UUID] = set()

    def add_resolution_handler(self, handler: ResolutionHandler) -> None:
        self._handlers.append(handler)

    async def create(
        self,
        *,
        task_id: UUID,
        session_id: UUID,
        action_summary: str,
        domain: str,
        reason: str,
        risk_level: RiskLevel,
        ttl_seconds: int,
        estimated_impact: str | None = None,
        is_demo: bool = False,
        purchase: PurchaseApprovalDetails | None = None,
        calendar: CalendarApprovalDetails | None = None,
    ) -> ApprovalRequest:
        now = self._clock()
        approval = ApprovalRequest(
            approval_id=uuid4(),
            task_id=task_id,
            session_id=session_id,
            action_summary=action_summary,
            domain=domain,
            reason=reason,
            risk_level=risk_level,
            status=ApprovalStatus.PENDING,
            estimated_impact=estimated_impact,
            expires_at=now + timedelta(seconds=ttl_seconds),
            is_demo=is_demo,
            created_at=now,
            purchase=purchase,
            calendar=calendar,
        )
        if self.persistence is not None and not is_demo:
            await self.persistence.approvals.save(approval, user_id=self.owner_for(task_id))  # authoritative record first
        async with self._lock:
            self._approvals[approval.approval_id] = approval
            while len(self._approvals) > self._max_items:
                self._approvals.popitem(last=False)
        await self._events.emit(
            session_id,
            TelemetryEventType.APPROVAL_REQUIRED,
            approval,
            task_id=task_id,
        )
        logger.info("approval.created", extra={"approval_id": str(approval.approval_id), "demo": is_demo})
        return approval

    def get(self, approval_id: UUID) -> ApprovalRequest:
        approval = self._approvals.get(approval_id)
        if approval is None:
            raise ApprovalNotFoundError(str(approval_id))
        return approval

    async def decide(self, approval_id: UUID, decision: ApprovalDecision) -> ApprovalRequest:
        expired: ApprovalRequest | None = None
        async with self._lock:
            approval = self._approvals.get(approval_id)
            if approval is None:
                raise ApprovalNotFoundError(str(approval_id))
            if approval.status != ApprovalStatus.PENDING:
                raise ApprovalAlreadyResolvedError(approval.status)
            now = self._clock()
            if now >= approval.expires_at:
                expired = self._resolve_locked(approval, ApprovalStatus.EXPIRED, None, now)
            else:
                status = (
                    ApprovalStatus.APPROVED
                    if decision == ApprovalDecision.APPROVE
                    else ApprovalStatus.REJECTED
                )
                resolved = self._resolve_locked(approval, status, decision, now)

        if expired is not None:
            await self._publish_resolution(expired)
            raise ApprovalExpiredError(str(approval_id))

        logger.info(
            "approval.decided",
            extra={"approval_id": str(approval_id), "decision": decision.value},
        )
        await self._publish_resolution(resolved)
        return resolved

    async def withdraw(self, approval_id: UUID, *, expired: bool = False) -> ApprovalRequest | None:
        """Close a still-pending request: WITHDRAWN when its run was stopped, EXPIRED when it timed out."""
        async with self._lock:
            approval = self._approvals.get(approval_id)
            if approval is None or approval.status != ApprovalStatus.PENDING:
                return None
            status = ApprovalStatus.EXPIRED if expired else ApprovalStatus.WITHDRAWN
            resolved = self._resolve_locked(approval, status, None, self._clock())
        await self._publish_resolution(resolved)
        return resolved

    async def expire_overdue(self) -> list[ApprovalRequest]:
        now = self._clock()
        async with self._lock:
            overdue = [
                self._resolve_locked(a, ApprovalStatus.EXPIRED, None, now)
                for a in list(self._approvals.values())
                if a.status == ApprovalStatus.PENDING and now >= a.expires_at
            ]
        for approval in overdue:
            await self._publish_resolution(approval)
        return overdue

    def _resolve_locked(
        self,
        approval: ApprovalRequest,
        status: ApprovalStatus,
        decision: ApprovalDecision | None,
        now: datetime,
    ) -> ApprovalRequest:
        resolved = approval.model_copy(
            update={"status": status, "decision": decision, "resolved_at": now}
        )
        self._approvals[approval.approval_id] = resolved
        return resolved

    def pending_count(self) -> int:
        return sum(1 for a in self._approvals.values() if a.status == ApprovalStatus.PENDING)

    def owner_for(self, task_id: UUID) -> UUID | None:
        return self.owner_lookup(task_id) if self.owner_lookup else None

    async def consume(self, approval_id: UUID) -> bool:
        """One-time use of an APPROVED approval (database-backed when persistence is on). True exactly once."""
        approval = self._approvals.get(approval_id)
        if approval is None or approval.status != ApprovalStatus.APPROVED:
            return False
        if self.persistence is not None and not approval.is_demo:
            return await self.persistence.approvals.consume(approval_id)
        async with self._lock:
            if approval_id in self._consumed:
                return False
            self._consumed.add(approval_id)
            return True

    async def _publish_resolution(self, approval: ApprovalRequest) -> None:
        assert approval.resolved_at is not None
        if self.persistence is not None and not approval.is_demo:
            await self.persistence.best_effort(self.persistence.approvals.save(approval), "approval.resolve")
        await self._events.emit(
            approval.session_id,
            TelemetryEventType.APPROVAL_RESOLVED,
            ApprovalResolvedPayload(
                approval_id=approval.approval_id,
                decision=approval.decision,
                status=approval.status,
                resolved_at=approval.resolved_at,
                is_demo=approval.is_demo,
            ),
            task_id=approval.task_id,
        )
        for handler in self._handlers:
            try:
                await handler(approval)
            except Exception:  # a faulty handler must never break the decision path
                logger.exception("approval.handler_failed", extra={"approval_id": str(approval.approval_id)})
