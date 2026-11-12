"""REST-facing commerce operations (thin layer over CommerceManager)."""

from __future__ import annotations

from uuid import UUID

from app.commerce.commerce_manager import CommerceManager, CommerceRequestError
from app.schemas.cart import CartSnapshot
from app.schemas.checkout import CheckoutSummary, OrderState
from app.schemas.commerce import ShoppingSummary


class CommerceService:
    def __init__(self, manager: CommerceManager | None, browser_exists: object) -> None:
        self._manager = manager
        self._browser_exists = browser_exists  # callable(session_id) -> bool

    @property
    def manager(self) -> CommerceManager:
        if self._manager is None:
            raise CommerceRequestError("COMMERCE_PLATFORM_UNSUPPORTED", "Commerce automation is disabled on this server.", 503)
        return self._manager

    def summary(self, task_id: UUID, session_id: UUID | None) -> ShoppingSummary:
        return self.manager.summary(task_id, session_id)

    def select(self, task_id: UUID, session_id: UUID, selection_id: UUID, candidate_id: UUID | None) -> None:
        self.manager.resolve_selection(task_id, session_id, selection_id, candidate_id)

    def _require_browser(self, session_id: UUID) -> None:
        if not self._browser_exists(session_id):  # type: ignore[operator]
            raise CommerceRequestError("BROWSER_SESSION_NOT_FOUND", "No browser is running for this session.", 404)

    def cart(self, session_id: UUID) -> CartSnapshot:
        self._require_browser(session_id)
        return self.manager.cart(session_id)

    async def refresh_cart(self, session_id: UUID) -> CartSnapshot:
        self._require_browser(session_id)
        return await self.manager.refresh_cart(session_id)

    async def update_quantity(self, session_id: UUID, item_id: UUID, quantity: int) -> CartSnapshot:
        self._require_browser(session_id)
        return await self.manager.update_quantity(session_id, item_id, quantity)

    async def checkout_review(self, task_id: UUID, session_id: UUID) -> CheckoutSummary:
        self._require_browser(session_id)
        return await self.manager.checkout_review(task_id, session_id)

    def checkout(self, task_id: UUID, session_id: UUID | None) -> CheckoutSummary:
        return self.manager.checkout_summary(task_id, session_id)

    def order_status(self, task_id: UUID, session_id: UUID | None) -> OrderState:
        return self.manager.order_status(task_id, session_id)
