"""Bridges runtime approval checkpoints to the existing ApprovalService.

The execution worker awaits a future (never an HTTP request). A decision only
resolves the waiter registered for that exact approval id AND task id, so a
decision can never be applied to another task. Only one pending approval may
exist per task.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from uuid import UUID

from app.schemas.calendar import CalendarApprovalDetails
from app.schemas.purchase import PurchaseApprovalDetails
from app.schemas.approval import ApprovalRequest, ApprovalStatus, RiskLevel
from app.services.approval_service import ApprovalService


class DuplicateApprovalError(RuntimeError):
    pass


@dataclass
class _Waiter:
    task_id: UUID
    future: asyncio.Future[ApprovalStatus]


class ApprovalCoordinator:
    def __init__(self, approvals: ApprovalService) -> None:
        self._approvals = approvals
        self._waiters: dict[UUID, _Waiter] = {}
        approvals.add_resolution_handler(self._on_resolved)

    async def create(
        self,
        *,
        task_id: UUID,
        session_id: UUID,
        action_summary: str,
        domain: str,
        reason: str,
        risk_level: RiskLevel,
        estimated_impact: str | None,
        ttl_seconds: int,
        purchase: PurchaseApprovalDetails | None = None,
        calendar: CalendarApprovalDetails | None = None,
    ) -> ApprovalRequest:
        if any(w.task_id == task_id and not w.future.done() for w in self._waiters.values()):
            raise DuplicateApprovalError("This task already has a pending approval.")
        approval = await self._approvals.create(
            task_id=task_id,
            session_id=session_id,
            action_summary=action_summary[:500],
            domain=domain[:253],
            reason=reason[:1000],
            risk_level=risk_level,
            estimated_impact=(estimated_impact or "")[:1000] or None,
            ttl_seconds=ttl_seconds,
            is_demo=False,
            purchase=purchase,
            calendar=calendar,
        )
        self._waiters[approval.approval_id] = _Waiter(task_id, asyncio.get_running_loop().create_future())
        return approval

    async def wait(self, approval_id: UUID, cancel_event: asyncio.Event, *, timeout: float) -> ApprovalStatus | None:
        """APPROVED / REJECTED / EXPIRED, or None if execution was cancelled while waiting."""
        waiter = self._waiters[approval_id]
        cancel_task = asyncio.ensure_future(cancel_event.wait())
        try:
            done, _ = await asyncio.wait({waiter.future, cancel_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if waiter.future in done:
                return waiter.future.result()
            # Cancelled or timed out: the pending request is withdrawn so it can never be approved later.
            timed_out = cancel_task not in done
            await self._approvals.withdraw(approval_id, expired=timed_out)
            return ApprovalStatus.EXPIRED if timed_out else None
        except asyncio.CancelledError:
            # The step itself was cancelled (Stop / shutdown): never leave an approvable request behind.
            if not waiter.future.done():
                with contextlib.suppress(Exception):
                    await asyncio.shield(self._approvals.withdraw(approval_id))
            raise
        finally:
            cancel_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancel_task
            self._waiters.pop(approval_id, None)

    async def _on_resolved(self, approval: ApprovalRequest) -> None:
        waiter = self._waiters.get(approval.approval_id)
        if waiter is None or waiter.task_id != approval.task_id or waiter.future.done():
            return
        waiter.future.set_result(approval.status)

    def pending_count(self) -> int:
        return sum(1 for w in self._waiters.values() if not w.future.done())
