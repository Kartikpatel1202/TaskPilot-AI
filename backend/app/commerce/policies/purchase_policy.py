"""Purchase policy — the ONLY path to an irreversible order, and only for Cash on Delivery.

An authorization is issued only when every condition holds, from trusted state:
- COD orders are enabled (COMMERCE_ALLOW_COD_ORDER_AFTER_APPROVAL) and prepaid automation is off;
- a real (non-demo) approval for THIS task is APPROVED, carries purchase details, and was
  decided within its validity window;
- the approval's summary hash equals the hash of the checkout summary re-read just now
  (any change to items, quantities, prices, fees, total, address or payment method => stale);
- the live summary is verified, its payment method is COD and its total is known;
- neither this approval nor this task has ever been used for a submission (single use).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from app.schemas.approval import ApprovalRequest, ApprovalStatus
from app.schemas.checkout import CheckoutSummary, PaymentMethod
from app.schemas.common import utc_now


class PurchaseBlockedError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class PurchaseAuthorization:
    task_id: UUID
    approval_id: UUID
    summary_hash: str
    expires_at: datetime
    token: str = field(default_factory=lambda: secrets.token_hex(16))
    consumed: bool = False  # the single submission is registered (before the click)
    clicked: bool = False   # the one allowed click has happened

    def usable(self) -> bool:
        return not self.clicked and utc_now() < self.expires_at

    def ready_to_click(self) -> bool:
        return self.consumed and self.usable()

    def mark_clicked(self) -> None:
        self.clicked = True


class PurchasePolicy:
    def __init__(self, *, allow_cod: bool, prepaid_automation: bool, approval_window_seconds: int) -> None:
        self._allow_cod = allow_cod
        self._prepaid = prepaid_automation
        self._window = approval_window_seconds
        self._used_approvals: set[UUID] = set()
        self._submitted_tasks: set[UUID] = set()

    def authorize(self, *, task_id: UUID, approval: ApprovalRequest | None, live: CheckoutSummary) -> PurchaseAuthorization:
        if self._prepaid:
            raise PurchaseBlockedError("PURCHASE_POLICY_BLOCKED", "Automated prepaid payment is not supported.")
        if not self._allow_cod:
            raise PurchaseBlockedError("PAYMENT_USER_HANDOFF_REQUIRED", "Automatic order placement is disabled; please place the order yourself.")
        if approval is None or approval.purchase is None or approval.is_demo:
            raise PurchaseBlockedError("PURCHASE_APPROVAL_REQUIRED", "A fresh, exact-order purchase approval is required.")
        if approval.task_id != task_id:
            raise PurchaseBlockedError("PURCHASE_POLICY_BLOCKED", "This approval belongs to a different task.")
        if approval.status == ApprovalStatus.EXPIRED:
            raise PurchaseBlockedError("PURCHASE_APPROVAL_EXPIRED", "The purchase approval expired.")
        if approval.status != ApprovalStatus.APPROVED:
            raise PurchaseBlockedError("PURCHASE_APPROVAL_REQUIRED", "The purchase was not approved.")
        decided = approval.resolved_at or approval.created_at
        if utc_now() - decided > timedelta(seconds=self._window):
            raise PurchaseBlockedError("PURCHASE_APPROVAL_EXPIRED", "The purchase approval is too old; please review again.")
        if approval.approval_id in self._used_approvals:
            raise PurchaseBlockedError("PURCHASE_APPROVAL_STALE", "This approval was already used and cannot be reused.")
        if task_id in self._submitted_tasks:
            raise PurchaseBlockedError("ORDER_SUBMISSION_UNKNOWN", "An order was already submitted for this task; it is never submitted twice.")
        if approval.purchase.summary_hash != live.summary_hash:
            raise PurchaseBlockedError("PURCHASE_APPROVAL_STALE", "The checkout changed after your approval; a fresh approval is needed.")
        if not live.is_verified or live.final_total is None:
            raise PurchaseBlockedError("COMMERCE_CHECKOUT_UNVERIFIED", "The checkout summary could not be fully verified.")
        if live.payment_method != PaymentMethod.COD or approval.purchase.payment_method != PaymentMethod.COD:
            raise PurchaseBlockedError("PAYMENT_USER_HANDOFF_REQUIRED", "Only Cash on Delivery orders can be placed for you; please pay yourself.")
        return PurchaseAuthorization(
            task_id=task_id, approval_id=approval.approval_id, summary_hash=live.summary_hash,
            expires_at=utc_now() + timedelta(seconds=60),
        )

    def consume(self, auth: PurchaseAuthorization) -> None:
        """Called immediately BEFORE the single submission click; it can never be repeated."""
        if auth.consumed or not auth.usable():
            raise PurchaseBlockedError("PURCHASE_APPROVAL_STALE", "This purchase authorization was already used or expired.")
        auth.consumed = True
        self._used_approvals.add(auth.approval_id)
        self._submitted_tasks.add(auth.task_id)

    def mark_approval_used(self, approval_id: UUID) -> None:
        self._used_approvals.add(approval_id)

    def was_submitted(self, task_id: UUID) -> bool:
        return task_id in self._submitted_tasks
