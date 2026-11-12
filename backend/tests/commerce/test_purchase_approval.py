"""Purchase policy + click policy: COD-only, exact-order, single-use, never payments."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.commerce.checkout.purchase_approval import approval_details
from app.commerce.policies.commerce_policy import ClickPurpose, CommercePolicy
from app.commerce.policies.purchase_policy import PurchaseBlockedError, PurchasePolicy
from app.schemas.approval import ApprovalRequest, ApprovalStatus, RiskLevel
from app.schemas.checkout import CheckoutSummary, PaymentMethod
from app.schemas.common import utc_now
from app.schemas.product import CommercePlatform

TASK = uuid4()


def summary(*, total: str = "252", method: PaymentMethod = PaymentMethod.COD, digest: str = "a" * 64, verified: bool = True) -> CheckoutSummary:
    return CheckoutSummary(checkout_id=uuid4(), task_id=TASK, platform=CommercePlatform.BLINKIT, items=[], final_total=Decimal(total),
                           payment_method=method, available_payment_methods=[PaymentMethod.COD, PaymentMethod.UPI],
                           masked_delivery_address="Home: •••, Gurugram 122•••", observed_at=utc_now(), is_verified=verified,
                           summary_hash=digest)


def approval(s: CheckoutSummary, *, status: ApprovalStatus = ApprovalStatus.APPROVED, task=TASK, demo: bool = False,  # type: ignore[no-untyped-def]
             age: int = 0, purchase: bool = True) -> ApprovalRequest:
    now = utc_now()
    return ApprovalRequest(approval_id=uuid4(), task_id=task, session_id=uuid4(), action_summary="Place order", domain="Blinkit",
                           reason="r", risk_level=RiskLevel.CRITICAL, status=status, expires_at=now + timedelta(seconds=60),
                           is_demo=demo, created_at=now - timedelta(seconds=age), resolved_at=now - timedelta(seconds=age),
                           purchase=approval_details(s) if purchase else None)


def policy(**kw) -> PurchasePolicy:  # type: ignore[no-untyped-def]
    return PurchasePolicy(allow_cod=kw.get("allow_cod", True), prepaid_automation=False, approval_window_seconds=300)


def test_exact_approved_cod_order_is_authorised_once() -> None:
    s = summary()
    p = policy()
    a = approval(s)
    auth = p.authorize(task_id=TASK, approval=a, live=summary())
    p.consume(auth)
    with pytest.raises(PurchaseBlockedError) as again:
        p.authorize(task_id=TASK, approval=a, live=summary())
    assert again.value.code == "PURCHASE_APPROVAL_STALE"  # an approval is never reused
    with pytest.raises(PurchaseBlockedError):
        p.consume(auth)  # and an authorisation is single-use


@pytest.mark.parametrize(("case", "code"), [
    ("generic", "PURCHASE_APPROVAL_REQUIRED"), ("demo", "PURCHASE_APPROVAL_REQUIRED"), ("rejected", "PURCHASE_APPROVAL_REQUIRED"),
    ("expired", "PURCHASE_APPROVAL_EXPIRED"), ("old", "PURCHASE_APPROVAL_EXPIRED"), ("other_task", "PURCHASE_POLICY_BLOCKED"),
    ("total_changed", "PURCHASE_APPROVAL_STALE"), ("unverified", "COMMERCE_CHECKOUT_UNVERIFIED"), ("prepaid", "PAYMENT_USER_HANDOFF_REQUIRED"),
])
def test_purchase_is_blocked_unless_every_condition_holds(case: str, code: str) -> None:
    s = summary()
    live = summary()
    a = approval(s)
    if case == "generic":
        a = approval(s, purchase=False)
    elif case == "demo":
        a = approval(s, demo=True)
    elif case == "rejected":
        a = approval(s, status=ApprovalStatus.REJECTED)
    elif case == "expired":
        a = approval(s, status=ApprovalStatus.EXPIRED)
    elif case == "old":
        a = approval(s, age=3600)
    elif case == "other_task":
        a = approval(s, task=uuid4())
    elif case == "total_changed":
        live = summary(total="292", digest="b" * 64)
    elif case == "unverified":
        live = summary(verified=False)
    elif case == "prepaid":
        s = summary(method=PaymentMethod.UPI)
        a, live = approval(s), summary(method=PaymentMethod.UPI)
    with pytest.raises(PurchaseBlockedError) as err:
        policy().authorize(task_id=TASK, approval=a, live=live)
    assert err.value.code == code


def test_cod_orders_can_be_disabled() -> None:
    s = summary()
    with pytest.raises(PurchaseBlockedError) as err:
        policy(allow_cod=False).authorize(task_id=TASK, approval=approval(s), live=s)
    assert err.value.code == "PAYMENT_USER_HANDOFF_REQUIRED"


def test_approval_details_need_an_observed_total() -> None:
    s = summary()
    s.final_total = None
    with pytest.raises(ValueError):
        approval_details(s)


# ---------------------------------------------------------------------- click policy

POLICY = CommercePolicy()


@pytest.mark.parametrize("label", ["Pay ₹252", "Pay now", "Proceed to Pay", "Pay with UPI", "Buy Now", "Place your order and pay"])
def test_payment_and_buy_controls_are_never_clickable(label: str) -> None:
    for purpose in ClickPurpose:
        assert not POLICY.check_click(purpose, label).allowed, (purpose, label)


def test_place_order_needs_cod_authorisation() -> None:
    assert not POLICY.check_click(ClickPurpose.PLACE_COD_ORDER, "Place your order").allowed
    assert not POLICY.check_click(ClickPurpose.ADD_TO_CART, "Place your order").allowed  # hard block outside the COD path
    p = policy()
    s = summary()
    auth = p.authorize(task_id=TASK, approval=approval(s), live=s)
    assert not POLICY.check_click(ClickPurpose.PLACE_COD_ORDER, "Place your order", authorization=auth).allowed  # not registered yet
    p.consume(auth)  # the single submission is recorded before any click
    assert POLICY.check_click(ClickPurpose.PLACE_COD_ORDER, "Place your order", authorization=auth).allowed
    auth.mark_clicked()
    assert not POLICY.check_click(ClickPurpose.PLACE_COD_ORDER, "Place your order", authorization=auth).allowed  # never twice


def test_checkout_navigation_and_cod_selection_are_narrow() -> None:
    assert POLICY.check_click(ClickPurpose.OPEN_CHECKOUT, "Proceed to Buy").allowed
    assert POLICY.check_click(ClickPurpose.OPEN_CHECKOUT, "Proceed to checkout").allowed
    assert not POLICY.check_click(ClickPurpose.OPEN_CHECKOUT, "Place Order").allowed
    assert POLICY.check_click(ClickPurpose.SELECT_COD, "Cash on Delivery/Pay on Delivery").allowed
    assert not POLICY.check_click(ClickPurpose.SELECT_COD, "UPI").allowed
    assert not POLICY.check_click(ClickPurpose.ADD_TO_CART, "Proceed to checkout").allowed


def test_shopping_clicks_still_pass_the_phase3_policy() -> None:
    assert POLICY.check_click(ClickPurpose.ADD_TO_CART, "ADD").allowed
    assert POLICY.check_click(ClickPurpose.ADD_TO_CART, "Add to Cart").allowed
    assert not POLICY.check_click(ClickPurpose.ADD_TO_CART, "Delete account").allowed
    assert not POLICY.check_click(ClickPurpose.ADD_TO_CART, "").allowed


def test_only_search_text_is_typed_never_credentials() -> None:
    assert POLICY.check_type("Search", "amul milk", sensitive=False).allowed
    assert not POLICY.check_type("Search", "my otp is 482913", sensitive=False).allowed
    assert not POLICY.check_type("Password", "hunter2", sensitive=True).allowed
