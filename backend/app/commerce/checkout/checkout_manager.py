"""Checkout review: open checkout from a verified cart and read the exact summary.

Reviewing never purchases anything. It requires a VERIFIED cart, stops at sign-in
walls (manual), and refuses to call the checkout verified if it differs from the
verified cart or a total/address cannot be read.
"""

from __future__ import annotations

from uuid import UUID

from app.commerce.base import CommerceAdapter, CommerceContext, CommerceError, SessionStatus
from app.commerce.checkout.checkout_inspector import compare_with_cart, read_summary
from app.schemas.cart import CartSnapshot, CartVerificationReport, CartVerificationStatus
from app.schemas.checkout import CheckoutSummary


class CheckoutManager:
    async def review(
        self, adapter: CommerceAdapter, ctx: CommerceContext, task_id: UUID,
        verification: CartVerificationReport | None, cart: CartSnapshot | None, previous: CheckoutSummary | None,
    ) -> CheckoutSummary:
        if verification is None or cart is None or verification.status != CartVerificationStatus.VERIFIED:
            raise CommerceError("COMMERCE_CART_UNVERIFIED", "Checkout review needs a fully verified cart first.", status="BLOCKED")
        status = await adapter.open_checkout(ctx)
        if status == SessionStatus.LOGIN_REQUIRED:
            raise CommerceError(
                "COMMERCE_SESSION_REQUIRED",
                f"{ctx.binding.name} asks you to sign in before checkout. Please sign in yourself (TaskPilot never types passwords or OTPs).",
                status="BLOCKED",
            )
        if status == SessionStatus.BLOCKED:
            raise CommerceError("CAPTCHA_REQUIRED", f"{ctx.binding.name} is showing a security check. Please continue yourself.", status="BLOCKED")
        summary = await read_summary(adapter, ctx, task_id)
        problems = compare_with_cart(summary, cart)
        summary.cart_id = cart.cart_id
        summary.version = (previous.version + 1) if previous else 1
        if problems:
            summary.warnings.extend(problems)
            summary.is_verified = False
        return summary
