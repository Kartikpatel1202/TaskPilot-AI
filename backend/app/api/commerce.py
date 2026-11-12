"""Phase 4 commerce endpoints. Everything returned was observed in the session's browser.

No endpoint here places an order: purchases happen only inside a running plan, after the
exact-order approval (POST /approvals/{id}/decision) and the purchase policy's re-check.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_commerce_service
from app.commerce.commerce_manager import CommerceRequestError
from app.schemas.cart import CartSnapshot
from app.schemas.checkout import CheckoutSummary, OrderState
from app.schemas.commerce import ProductSelectionRequest, QuantityUpdateRequest, SessionOwnedRequest, ShoppingSummary
from app.schemas.common import APIError
from app.services.commerce_service import CommerceService

router = APIRouter(tags=["commerce"])
ERRORS = {403: {"model": APIError}, 404: {"model": APIError}, 409: {"model": APIError}, 503: {"model": APIError}}


def _same_session(path_id: UUID, body_id: UUID) -> None:
    if path_id != body_id:
        raise CommerceRequestError("TASK_SESSION_MISMATCH", "The session in the request body does not match the URL.", 403)


@router.get("/tasks/{task_id}/commerce/summary", response_model=ShoppingSummary, responses=ERRORS)
async def commerce_summary(task_id: UUID, session_id: UUID | None = Query(default=None),
                           service: CommerceService = Depends(get_commerce_service)) -> ShoppingSummary:
    return service.summary(task_id, session_id)


@router.post("/tasks/{task_id}/commerce/selection", status_code=status.HTTP_202_ACCEPTED, responses=ERRORS)
async def choose_product(task_id: UUID, body: ProductSelectionRequest, service: CommerceService = Depends(get_commerce_service)) -> dict[str, object]:
    """Answer a pending product choice (candidate_id null = skip this product)."""
    service.select(task_id, body.session_id, body.selection_id, body.candidate_id)
    return {"accepted": True, "selection_id": str(body.selection_id)}


@router.get("/browser/sessions/{session_id}/commerce/cart", response_model=CartSnapshot, responses=ERRORS)
async def commerce_cart(session_id: UUID, service: CommerceService = Depends(get_commerce_service)) -> CartSnapshot:
    return service.cart(session_id)


@router.post("/browser/sessions/{session_id}/commerce/cart/refresh", response_model=CartSnapshot, responses=ERRORS)
async def refresh_cart(session_id: UUID, body: SessionOwnedRequest, service: CommerceService = Depends(get_commerce_service)) -> CartSnapshot:
    _same_session(session_id, body.session_id)
    return await service.refresh_cart(session_id)


@router.post("/browser/sessions/{session_id}/commerce/cart/items/{item_id}/quantity", response_model=CartSnapshot, responses=ERRORS)
async def update_quantity(session_id: UUID, item_id: UUID, body: QuantityUpdateRequest,
                          service: CommerceService = Depends(get_commerce_service)) -> CartSnapshot:
    _same_session(session_id, body.session_id)
    return await service.update_quantity(session_id, item_id, body.quantity)


@router.post("/tasks/{task_id}/commerce/checkout/review", response_model=CheckoutSummary, responses=ERRORS)
async def checkout_review(task_id: UUID, body: SessionOwnedRequest, service: CommerceService = Depends(get_commerce_service)) -> CheckoutSummary:
    """Read the live checkout summary (never purchases)."""
    return await service.checkout_review(task_id, body.session_id)


@router.get("/tasks/{task_id}/commerce/checkout", response_model=CheckoutSummary, responses=ERRORS)
async def checkout_summary(task_id: UUID, session_id: UUID | None = Query(default=None),
                           service: CommerceService = Depends(get_commerce_service)) -> CheckoutSummary:
    return service.checkout(task_id, session_id)


@router.get("/tasks/{task_id}/commerce/order-status", response_model=OrderState, responses=ERRORS)
async def order_status(task_id: UUID, session_id: UUID | None = Query(default=None),
                       service: CommerceService = Depends(get_commerce_service)) -> OrderState:
    return service.order_status(task_id, session_id)
