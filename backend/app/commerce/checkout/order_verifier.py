"""Order state from what the website visibly shows after the single submission.

An order is CONFIRMED only when a confirmation is visible on the page; an order
reference is recorded only when the page shows one. Otherwise the state is UNKNOWN
and the user is asked to check the website — the submission is never repeated.
"""

from __future__ import annotations

from uuid import UUID

from app.commerce.base import OrderSubmission
from app.schemas.checkout import OrderState, OrderStatus
from app.schemas.common import utc_now


def order_state(task_id: UUID, submission: OrderSubmission, *, checkout_id: UUID | None, approval_id: UUID | None) -> OrderState:
    if submission.confirmed:
        return OrderState(
            task_id=task_id, status=OrderStatus.CONFIRMED, order_reference=submission.order_reference,
            message="The website shows the order as placed" + (f" (reference {submission.order_reference})." if submission.order_reference else "."),
            checkout_id=checkout_id, approval_id=approval_id, observed_at=utc_now(),
        )
    return OrderState(
        task_id=task_id, status=OrderStatus.UNKNOWN, message=submission.message,
        checkout_id=checkout_id, approval_id=approval_id, observed_at=utc_now(),
    )
