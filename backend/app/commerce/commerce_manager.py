"""CommerceManager — coordinates shopping workflows on top of the Phase 3 execution engine.

Plan steps of type `commerce` are executed here (via the `commerce` action handler).
Everything shown to the user comes from observed pages; every irreversible step is
gated by the purchase policy and an exact-order approval; one task runs at a time per
browser session (the execution queue + session lock guarantee this).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from app.commerce.base import CommerceContext, CommerceError, ProductSelection, SessionStatus, SiteBinding
from app.commerce.cart.cart_manager import CartManager
from app.commerce.cart.cart_verifier import CartVerifier
from app.commerce.checkout.checkout_manager import CheckoutManager
from app.commerce.checkout.order_verifier import order_state
from app.commerce.checkout.purchase_approval import approval_details, approval_text
from app.commerce.matching.product_matcher import MatchThresholds, ProductMatcher
from app.commerce.money import format_inr
from app.commerce.policies.commerce_policy import CommercePolicy
from app.commerce.policies.price_change_policy import PriceChangePolicy
from app.commerce.policies.purchase_policy import PurchaseBlockedError, PurchasePolicy
from app.commerce.registry import CommerceRegistry
from app.commerce.search.product_search import search_with_retries
from app.core.logging import get_logger
from app.execution.execution_result import ActionExecutionStatus, ActionResult
from app.schemas.approval import ApprovalStatus, RiskLevel
from app.schemas.cart import CartSnapshot, CartVerificationStatus
from app.schemas.checkout import CheckoutSummary, OrderState, OrderStatus, PaymentMethod
from app.schemas.commerce import (
    CartChangePayload,
    CartVerificationPayload,
    CheckoutReadyPayload,
    CommerceAction,
    CommerceFailedPayload,
    CommerceSearchPayload,
    CommerceSessionPayload,
    PendingSelection,
    PriceChangedPayload,
    ProductDecisionPayload,
    ProductsFoundPayload,
    PurchaseStatusPayload,
    RequirementProgress,
    RequirementStatus,
    ShoppingSummary,
    WorkflowStatus,
)
from app.schemas.common import utc_now
from app.schemas.execution import ExecutionPausedPayload, ExecutionResumedPayload
from app.schemas.product import MatchDecision, ProductCandidate
from app.schemas.task import TaskState
from app.schemas.telemetry import TelemetryEventType as E

if TYPE_CHECKING:
    from app.browser.controller import BrowserController
    from app.browser.manager import BrowserManager
    from app.config import Settings
    from app.core.execution_events import ExecutionEvents
    from app.execution.approval_coordinator import ApprovalCoordinator
    from app.execution.execution_context import ExecutionContext
    from app.services.approval_service import ApprovalService

logger = get_logger("commerce.manager")
MAX_APPROVAL_ROUNDS = 2


class CommerceRequestError(Exception):
    """REST-level commerce error (mapped to the standard API error format)."""

    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass
class Workflow:
    task_id: UUID
    session_id: UUID
    binding: SiteBinding
    summary: ShoppingSummary
    candidates: dict[UUID, ProductCandidate] = field(default_factory=dict)
    selection_future: asyncio.Future[UUID | None] | None = None


class CommerceManager:
    def __init__(
        self, *, settings: Settings, registry: CommerceRegistry, browser: BrowserManager, controller: BrowserController,
        telemetry: ExecutionEvents, approvals: ApprovalCoordinator, approval_service: ApprovalService,
    ) -> None:
        self.settings = settings
        self.rate_limiter: Any = None  # Phase 6 (set by the container)
        self.registry = registry
        self._browser = browser
        self._controller = controller
        self._telemetry = telemetry
        self._approvals = approvals
        self._approval_service = approval_service
        self.policy = CommercePolicy()
        self.matcher = ProductMatcher(MatchThresholds(
            exact=settings.commerce_exact_match_threshold, acceptable=settings.commerce_acceptable_match_threshold,
            margin=settings.commerce_ambiguity_margin, max_packs=settings.commerce_max_packs_per_item,
        ))
        self.prices = PriceChangePolicy(settings.commerce_max_price_change_percent)
        self.carts = CartManager(self.prices)
        self.verifier = CartVerifier(self.matcher)
        self.checkout = CheckoutManager()
        self.purchase = PurchasePolicy(
            allow_cod=settings.commerce_allow_cod_order_after_approval,
            prepaid_automation=settings.commerce_automated_prepaid_payment,
            approval_window_seconds=settings.execution_approval_ttl_seconds,
        )
        self._workflows: OrderedDict[UUID, Workflow] = OrderedDict()
        self._session_carts: dict[UUID, CartSnapshot] = {}
        self._session_platform: dict[UUID, str] = {}

    # ---------------------------------------------------------------- contexts and state

    def _cctx(self, session_id: UUID, task_id: UUID | None, binding: SiteBinding, cancel: asyncio.Event | None = None) -> CommerceContext:
        return CommerceContext(
            session_id=session_id, task_id=task_id, controller=self._controller, policy=self.policy, telemetry=self._telemetry,
            binding=binding, search_timeout=self.settings.commerce_search_timeout_seconds,
            max_results=self.settings.commerce_max_search_results, max_attempts=self.settings.commerce_max_search_attempts,
            cancel_event=cancel or asyncio.Event(),
        )

    def _workflow(self, ctx: ExecutionContext, action: CommerceAction) -> Workflow:
        wf = self._workflows.get(ctx.task_id)
        if wf is not None:
            return wf
        binding = self.registry.binding(action.site_key)
        if binding is None or binding.platform != action.platform:
            raise CommerceError("COMMERCE_PLATFORM_UNSUPPORTED", "This shopping site is not supported.", status="BLOCKED")
        progress = [
            RequirementProgress(requirement=s.action.requirement)
            for s in ctx.plan.steps
            if getattr(s.action, "type", None) == "commerce" and s.action.requirement is not None  # type: ignore[union-attr]
        ]
        summary = ShoppingSummary(
            task_id=ctx.task_id, session_id=ctx.session_id, platform=binding.platform, site_name=binding.name,
            is_fixture=binding.is_fixture, status=WorkflowStatus.RUNNING, requirements=progress, updated_at=utc_now(),
        )
        wf = Workflow(ctx.task_id, ctx.session_id, binding, summary)
        self._workflows[ctx.task_id] = wf
        while len(self._workflows) > 200:
            self._workflows.popitem(last=False)
        self._session_platform[ctx.session_id] = binding.key
        return wf

    @staticmethod
    def _touch(wf: Workflow, status: WorkflowStatus | None = None, message: str | None = None) -> None:
        if status is not None:
            wf.summary.status = status
        if message is not None:
            wf.summary.message = message
        wf.summary.updated_at = utc_now()

    def _progress(self, wf: Workflow, req_id: UUID) -> RequirementProgress:
        return next(p for p in wf.summary.requirements if p.requirement.product_id == req_id)

    # ---------------------------------------------------------------- plan step entry point

    async def run_step(self, ctx: ExecutionContext, action: CommerceAction) -> ActionResult:
        if not self.settings.commerce_enabled:
            return ctx.result(ActionExecutionStatus.BLOCKED, "Commerce automation is disabled.", error_code="COMMERCE_PLATFORM_UNSUPPORTED")
        try:
            wf = self._workflow(ctx, action)
            cctx = self._cctx(ctx.session_id, ctx.task_id, wf.binding, ctx.cancel_event)
            handler = {
                "open_store": self._open_store, "search_products": self._search_only, "search_and_add": self._search_and_add,
                "verify_cart": self._verify_cart, "checkout_review": self._checkout_review, "place_order": self._place_order,
            }[action.operation]
            return await handler(ctx, cctx, wf, action)
        except CommerceError as exc:
            wf_opt = self._workflows.get(ctx.task_id)
            if wf_opt is not None and exc.code != "PURCHASE_REJECTED":  # a rejection keeps its own "cart still prepared" state
                self._touch(wf_opt, WorkflowStatus.BLOCKED if exc.status == "BLOCKED" else WorkflowStatus.FAILED, exc.message)
                if exc.code not in ("COMMERCE_PRODUCT_NOT_FOUND", "COMMERCE_PRODUCT_AMBIGUOUS"):
                    await self._emit(ctx, E.COMMERCE_WORKFLOW_FAILED, CommerceFailedPayload(platform=action.platform, code=exc.code, message=exc.message))
            status = ActionExecutionStatus.BLOCKED if exc.status == "BLOCKED" else ActionExecutionStatus.FAILED
            return ctx.result(status, exc.message, error_code=exc.code)

    async def _emit(self, ctx: ExecutionContext | CommerceContext, event: Any, payload: Any) -> None:
        await self._telemetry.emit(ctx.session_id, event, payload, task_id=ctx.task_id)

    # ---------------------------------------------------------------- open store

    async def _open_store(self, ctx: ExecutionContext, cctx: CommerceContext, wf: Workflow, action: CommerceAction) -> ActionResult:
        adapter = self.registry.adapter(wf.binding.platform)
        status = await adapter.open_store(cctx)
        await self._emit(ctx, E.COMMERCE_SESSION_DETECTED, CommerceSessionPayload(
            platform=wf.binding.platform, site_name=wf.binding.name, is_fixture=wf.binding.is_fixture, status=status.value,
            message={"READY": f"{wf.binding.name} is open.", "LOGIN_REQUIRED": "Signed out — browsing works; checkout will need your sign-in.",
                     "LOCATION_REQUIRED": "A delivery location is needed.", "BLOCKED": "The site is showing a security check."}[status.value],
        ))
        if status == SessionStatus.LOCATION_REQUIRED:
            await self._emit(ctx, E.COMMERCE_LOCATION_REQUIRED, CommerceSessionPayload(
                platform=wf.binding.platform, site_name=wf.binding.name, is_fixture=wf.binding.is_fixture, status=status.value,
                message=("Please choose your delivery location in the browser window — I'll wait for you. "
                         "TaskPilot never invents an address.") if not ctx.controller.manager.headless else
                        "Please choose your delivery location on the site yourself; TaskPilot never invents an address.",
            ))
        await adapter.require_ready(cctx)  # type: ignore[attr-defined]
        if any(p.requirement for p in wf.summary.requirements) or action.payment_preference:
            # Read the existing cart once so later additions only add what is missing.
            snapshot = await adapter.inspect_cart(cctx)
            self._session_carts[ctx.session_id] = snapshot
            wf.summary.cart = snapshot
            await adapter.open_store(cctx)
        self._touch(wf, WorkflowStatus.RUNNING, f"{wf.binding.name} ready.")
        cart_note = f" Existing cart: {wf.summary.cart.item_count} item(s)." if wf.summary.cart else ""
        return ctx.result(ActionExecutionStatus.SUCCEEDED, f"Opened {wf.binding.name}.{cart_note}", verified=True)

    # ---------------------------------------------------------------- search

    async def _search_and_rank(self, ctx: ExecutionContext, cctx: CommerceContext, wf: Workflow, entry: RequirementProgress) -> tuple[Any, list[ProductCandidate]]:
        req = entry.requirement
        if self.rate_limiter is not None and not await self.rate_limiter.hit(
                f"cs:{ctx.user_id or ctx.session_id}", self.settings.commerce_searches_per_minute, 60):
            raise CommerceError("RATE_LIMITED", "Too many product searches in the last minute. Please try again shortly.", status="BLOCKED")
        adapter = self.registry.adapter(wf.binding.platform)
        entry.status = RequirementStatus.SEARCHING
        self._touch(wf)
        await self._emit(ctx, E.COMMERCE_SEARCH_STARTED, CommerceSearchPayload(platform=wf.binding.platform, requirement_id=req.product_id,
                                                                                query=req.query, message=f"Searching {wf.binding.name} for {req.query}…"))
        candidates = await search_with_retries(adapter, req, cctx)
        for c in candidates:
            wf.candidates[c.candidate_id] = c
        result = self.matcher.match(req, candidates)
        entry.candidates = candidates
        entry.matches = result.ranked
        entry.decision = result.decision
        await self._emit(ctx, E.COMMERCE_SEARCH_COMPLETED, CommerceSearchPayload(platform=wf.binding.platform, requirement_id=req.product_id,
                                                                                  query=req.query, message=f"{len(candidates)} product(s) read."))
        await self._emit(ctx, E.COMMERCE_PRODUCTS_FOUND, ProductsFoundPayload(
            platform=wf.binding.platform, requirement_id=req.product_id, query=req.query, candidate_count=len(candidates),
            exact_match_count=sum(1 for m in result.ranked if m.exact_match),
        ))
        return result, candidates

    async def _search_only(self, ctx: ExecutionContext, cctx: CommerceContext, wf: Workflow, action: CommerceAction) -> ActionResult:
        assert action.requirement is not None
        entry = self._progress(wf, action.requirement.product_id)
        result, candidates = await self._search_and_rank(ctx, cctx, wf, entry)
        suitable = [m for m in result.ranked if not m.disqualified and m.overall_score >= self.settings.commerce_acceptable_match_threshold]
        if not suitable:
            entry.status = RequirementStatus.NOT_FOUND
            entry.message = result.message
            self._touch(wf, WorkflowStatus.SEARCH_COMPLETE, entry.message)
            return ctx.result(ActionExecutionStatus.FAILED, f"No listing matched every requirement for {action.requirement.label()} "
                              f"({len(candidates)} read).", error_code="COMMERCE_PRODUCT_NOT_FOUND")
        entry.status = RequirementStatus.FOUND
        excluded = len(result.ranked) - len(suitable)
        entry.message = f"{len(suitable)} suitable option(s); {excluded} excluded (wrong spec, over budget or unavailable). Nothing was added to the cart."
        self._touch(wf, WorkflowStatus.SEARCH_COMPLETE, entry.message)
        top = [wf.candidates[m.candidate_id] for m in suitable[:5]]
        return ctx.result(ActionExecutionStatus.SUCCEEDED, entry.message, verified=True, extracted_data={
            "source": "observed_dom", "item_count": len(top),
            "items": [{"name": c.product_name[:120], "price": c.displayed_price, "rating": c.rating, "seller": c.seller} for c in top],
            "missing_fields": [],
        })

    async def _search_and_add(self, ctx: ExecutionContext, cctx: CommerceContext, wf: Workflow, action: CommerceAction) -> ActionResult:
        assert action.requirement is not None
        req = action.requirement
        entry = self._progress(wf, req.product_id)
        result, candidates = await self._search_and_rank(ctx, cctx, wf, entry)

        chosen_id: UUID | None = None
        if result.decision == MatchDecision.SELECTED and result.selected:
            chosen_id = result.selected.candidate_id
        elif result.decision in (MatchDecision.AMBIGUOUS, MatchDecision.NEEDS_CONFIRMATION):
            options = [m for m in result.ranked if not m.disqualified][:8]
            chosen_id = await self._ask_selection(ctx, wf, entry, [m.candidate_id for m in options], result.message)
            if chosen_id is None:
                entry.status = RequirementStatus.SKIPPED
                entry.message = "Not added — no product was chosen."
                self._touch(wf)
                return ctx.result(ActionExecutionStatus.FAILED, f"{req.label()}: {entry.message}", error_code="COMMERCE_PRODUCT_AMBIGUOUS")
        else:
            unavailable = result.decision == MatchDecision.UNAVAILABLE
            entry.status = RequirementStatus.UNAVAILABLE if unavailable else RequirementStatus.NOT_FOUND
            entry.message = result.message
            self._touch(wf)
            await self._emit(ctx, E.COMMERCE_PRODUCT_UNAVAILABLE, ProductDecisionPayload(
                platform=wf.binding.platform, requirement_id=req.product_id, decision=result.decision, message=result.message,
                candidate_count=len(candidates),
            ))
            return ctx.result(ActionExecutionStatus.FAILED, result.message, error_code="COMMERCE_PRODUCT_NOT_FOUND")

        cand = wf.candidates[chosen_id]
        match = self.matcher.score(req, cand)
        packs = match.packs_needed or 1
        entry.selected_candidate_id = chosen_id
        entry.status = RequirementStatus.SELECTED
        await self._emit(ctx, E.COMMERCE_PRODUCT_SELECTED, ProductDecisionPayload(
            platform=wf.binding.platform, requirement_id=req.product_id, product_name=cand.product_name[:200], decision=MatchDecision.SELECTED,
            message=f"{cand.product_name[:80]} {cand.pack_size or ''} × {packs} — {match.explanation}".strip(), candidate_count=len(candidates),
        ))
        await self._emit(ctx, E.COMMERCE_CART_UPDATE_STARTED, CartChangePayload(platform=wf.binding.platform, requirement_id=req.product_id,
                                                                                product_name=cand.product_name[:200], message=f"Adding {packs} pack(s)…"))
        adapter = self.registry.adapter(wf.binding.platform)
        mutation = await self.carts.ensure_quantity(adapter, ProductSelection(cand, packs, req), cctx, self._session_carts.get(ctx.session_id))
        if not mutation.success:
            entry.status = RequirementStatus.FAILED
            entry.message = mutation.message
            self._touch(wf)
            return ctx.result(ActionExecutionStatus.FAILED, mutation.message, error_code=mutation.error_code or "COMMERCE_QUANTITY_MISMATCH")
        entry.packs_added = mutation.added_packs
        entry.status = RequirementStatus.ALREADY_IN_CART if mutation.added_packs == 0 else RequirementStatus.ADDED
        entry.message = mutation.message
        self._touch(wf)
        await self._emit(ctx, E.COMMERCE_CART_ITEM_ADDED if mutation.added_packs else E.COMMERCE_CART_ITEM_UPDATED, CartChangePayload(
            platform=wf.binding.platform, requirement_id=req.product_id, product_name=cand.product_name[:200],
            before_quantity=mutation.before_quantity, after_quantity=mutation.after_quantity, message=mutation.message,
        ))
        return ctx.result(ActionExecutionStatus.SUCCEEDED, mutation.message, verified=True)

    async def _ask_selection(self, ctx: ExecutionContext, wf: Workflow, entry: RequirementProgress, options: list[UUID], question: str) -> UUID | None:
        if not options:
            return None
        timeout = self.settings.commerce_selection_timeout_seconds
        selection = PendingSelection(selection_id=uuid4(), task_id=ctx.task_id, requirement_id=entry.requirement.product_id,
                                     question=question, candidate_ids=options, expires_at=utc_now() + timedelta(seconds=timeout))
        loop = asyncio.get_running_loop()
        wf.selection_future = loop.create_future()
        wf.summary.pending_selection = selection
        entry.status = RequirementStatus.AWAITING_SELECTION
        self._touch(wf, WorkflowStatus.WAITING_USER, question)
        await self._emit(ctx, E.COMMERCE_PRODUCT_AMBIGUOUS, ProductDecisionPayload(
            platform=wf.binding.platform, requirement_id=entry.requirement.product_id, decision=entry.decision or MatchDecision.AMBIGUOUS,
            message=question, selection_id=selection.selection_id, candidate_count=len(options),
        ))
        step = ctx.current_step
        await ctx.tasks.transition(ctx.task_id, TaskState.WAITING_APPROVAL, reason="Waiting for you to choose a product")
        if step is not None:
            await self._emit(ctx, E.TASK_EXECUTION_PAUSED, ExecutionPausedPayload(step_id=step.step_id, reason=question[:900]))
        cancel = asyncio.ensure_future(ctx.cancel_event.wait())
        try:
            done, _ = await asyncio.wait({wf.selection_future, cancel}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            chosen = wf.selection_future.result() if wf.selection_future in done else None
        finally:
            cancel.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancel
            wf.summary.pending_selection = None
            wf.selection_future = None
        if ctx.cancel_event.is_set():
            raise CommerceError("USER_CANCELLED", "Stopped by you while choosing a product.", status="BLOCKED")
        await ctx.tasks.transition(ctx.task_id, TaskState.EXECUTING, reason="Product choice received" if chosen else "No product chosen")
        if step is not None:
            await self._emit(ctx, E.TASK_EXECUTION_RESUMED, ExecutionResumedPayload(step_id=step.step_id, message="Continuing with your choice."))
        self._touch(wf, WorkflowStatus.RUNNING)
        return chosen if chosen in options else None

    def resolve_selection(self, task_id: UUID, session_id: UUID, selection_id: UUID, candidate_id: UUID | None) -> None:
        wf = self._workflows.get(task_id)
        if wf is None or wf.session_id != session_id:
            raise CommerceRequestError("TASK_SESSION_MISMATCH" if wf else "COMMERCE_SESSION_REQUIRED", "No such shopping task for this session.",
                                       403 if wf else 404)
        pending = wf.summary.pending_selection
        if pending is None or pending.selection_id != selection_id or wf.selection_future is None or wf.selection_future.done():
            raise CommerceRequestError("COMMERCE_SELECTION_NOT_PENDING", "This product choice is no longer pending.", 409)
        if candidate_id is not None and candidate_id not in pending.candidate_ids:
            raise CommerceRequestError("COMMERCE_PRODUCT_AMBIGUOUS", "That product was not one of the offered options.", 422)
        wf.selection_future.set_result(candidate_id)

    # ---------------------------------------------------------------- verification

    async def _verify_cart(self, ctx: ExecutionContext, cctx: CommerceContext, wf: Workflow, action: CommerceAction) -> ActionResult:
        adapter = self.registry.adapter(wf.binding.platform)
        await self._emit(ctx, E.COMMERCE_CART_VERIFICATION_STARTED, CartChangePayload(platform=wf.binding.platform, message="Reading the cart…"))
        try:
            snapshot = await asyncio.wait_for(adapter.inspect_cart(cctx), timeout=self.settings.commerce_cart_verification_timeout_seconds + 15)
        except asyncio.TimeoutError as exc:
            raise CommerceError("COMMERCE_CART_UNVERIFIED", "The cart could not be read in time.") from exc
        report = self.verifier.verify(ctx.task_id, wf.summary.requirements, snapshot)
        snapshot.verification_status = report.status
        self._session_carts[ctx.session_id] = snapshot
        wf.summary.cart = snapshot
        wf.summary.verification = report
        for change in self.carts.price_changes(
            {str(p.selected_candidate_id): wf.candidates[p.selected_candidate_id] for p in wf.summary.requirements if p.selected_candidate_id}, snapshot
        ):
            wf.summary.price_changes.append(change.message())
            await self._emit(ctx, E.COMMERCE_PRICE_CHANGED, PriceChangedPayload(
                platform=wf.binding.platform, product_name=change.label[:200], previous=change.previous, current=change.current,
                difference=change.difference, message=change.message(),
            ))
        payload = CartVerificationPayload(
            status=report.status, requested_item_count=len(report.requested_items),
            matched_item_count=sum(1 for c in report.checks if c.status == "OK"),
            missing_items=report.missing_items, mismatched_items=report.mismatched_items, warnings=report.warnings[:10],
        )
        totals = f" Cart total shown: {format_inr(snapshot.total)}." if snapshot.total is not None else (
            f" Item subtotal: {format_inr(snapshot.subtotal)}; fees appear at checkout." if snapshot.subtotal is not None else "")
        if report.status == CartVerificationStatus.VERIFIED:
            await self._emit(ctx, E.COMMERCE_CART_VERIFICATION_COMPLETED, payload)
            self._touch(wf, WorkflowStatus.CART_READY, "Cart verified. No order has been placed.")
            return ctx.result(ActionExecutionStatus.SUCCEEDED, f"Cart verified: all {payload.matched_item_count} item(s) match.{totals} No order placed.",
                              verified=True, extracted_data=_cart_extract(snapshot))
        await self._emit(ctx, E.COMMERCE_CART_VERIFICATION_FAILED, payload)
        partial = report.status == CartVerificationStatus.PARTIAL
        self._touch(wf, WorkflowStatus.PARTIAL if partial else WorkflowStatus.FAILED,
                    "Cart is only partly prepared." if partial else "The cart does not match the request.")
        detail = "; ".join([*report.missing_items[:3], *report.mismatched_items[:3]])
        return ctx.result(ActionExecutionStatus.FAILED, f"Cart {report.status.value.lower()}: {detail or 'nothing to verify'}.{totals}",
                          error_code="COMMERCE_CART_UNVERIFIED", extracted_data=_cart_extract(snapshot))

    # ---------------------------------------------------------------- checkout review

    async def _checkout_review(self, ctx: ExecutionContext, cctx: CommerceContext, wf: Workflow, action: CommerceAction) -> ActionResult:
        summary = await self._review(cctx, wf)
        if not summary.is_verified:
            return ctx.result(ActionExecutionStatus.FAILED, "Checkout could not be verified: " + "; ".join(summary.warnings[:3]),
                              error_code="COMMERCE_CHECKOUT_UNVERIFIED")
        return ctx.result(ActionExecutionStatus.SUCCEEDED,
                          f"Checkout reviewed: {len(summary.items)} item(s), total {format_inr(summary.final_total)}, "
                          f"deliver to {summary.masked_delivery_address or 'unknown'}. Nothing was purchased.", verified=True)

    async def _review(self, cctx: CommerceContext, wf: Workflow) -> CheckoutSummary:
        adapter = self.registry.adapter(wf.binding.platform)
        previous = wf.summary.checkout
        summary = await self.checkout.review(adapter, cctx, wf.task_id, wf.summary.verification, wf.summary.cart, previous)
        if wf.summary.cart is not None:
            change = self.prices.compare("Cart subtotal", wf.summary.cart.subtotal, summary.subtotal)
            if change:
                summary.warnings.append(change.message())
                wf.summary.price_changes.append(change.message())
                await self._emit(cctx, E.COMMERCE_PRICE_CHANGED, PriceChangedPayload(platform=wf.binding.platform, previous=change.previous,
                                 current=change.current, difference=change.difference, message=change.message()))
        wf.summary.checkout = summary
        wf.summary.order = OrderState(task_id=wf.task_id, status=OrderStatus.REVIEW_REQUIRED, checkout_id=summary.checkout_id,
                                      message="Checkout reviewed. No order has been placed.")
        self._touch(wf, WorkflowStatus.CHECKOUT_READY, "Checkout reviewed. No order has been placed.")
        await self._emit(cctx, E.COMMERCE_CHECKOUT_REVIEW_READY, CheckoutReadyPayload(
            platform=wf.binding.platform, checkout_id=summary.checkout_id, final_total=summary.final_total,
            payment_method=summary.payment_method.value, is_verified=summary.is_verified, item_count=len(summary.items),
        ))
        return summary

    # ---------------------------------------------------------------- purchase

    async def _handoff(self, ctx: ExecutionContext, wf: Workflow, message: str) -> ActionResult:
        wf.summary.order = OrderState(task_id=wf.task_id, status=OrderStatus.PAYMENT_HANDOFF, message=message,
                                      checkout_id=wf.summary.checkout.checkout_id if wf.summary.checkout else None)
        self._touch(wf, WorkflowStatus.PAYMENT_HANDOFF, message)
        await self._emit(ctx, E.COMMERCE_PAYMENT_HANDOFF, PurchaseStatusPayload(
            platform=wf.binding.platform, status="USER_ACTION_REQUIRED", message=message,
            checkout_id=wf.summary.checkout.checkout_id if wf.summary.checkout else None,
            final_total=wf.summary.checkout.final_total if wf.summary.checkout else None,
        ))
        return ctx.result(ActionExecutionStatus.SUCCEEDED, message + " No payment was made by TaskPilot.", verified=True)

    async def _place_order(self, ctx: ExecutionContext, cctx: CommerceContext, wf: Workflow, action: CommerceAction) -> ActionResult:
        summary = wf.summary.checkout
        if summary is None or not summary.is_verified:
            raise CommerceError("COMMERCE_CHECKOUT_UNVERIFIED", "A verified checkout review is required before ordering.", status="BLOCKED")
        if self.purchase.was_submitted(ctx.task_id):
            raise CommerceError("ORDER_SUBMISSION_UNKNOWN", "An order was already submitted for this task; it is never submitted twice.", status="BLOCKED")
        pref = action.payment_preference or "ANY"
        if pref != "COD":
            return await self._handoff(ctx, wf, f"Checkout is ready ({format_inr(summary.final_total)}). Please choose a payment method and pay "
                                                f"yourself on {wf.binding.name}.")
        if not self.settings.commerce_allow_cod_order_after_approval:
            return await self._handoff(ctx, wf, "Automatic cash-on-delivery orders are disabled here. Please place the order yourself.")
        if PaymentMethod.COD not in summary.available_payment_methods:
            return await self._handoff(ctx, wf, "Cash on Delivery is not available for this order. Decide whether to pay another way — "
                                                "TaskPilot will not pay for you.")
        adapter = self.registry.adapter(wf.binding.platform)
        if not await adapter.select_payment_method(PaymentMethod.COD, cctx):
            return await self._handoff(ctx, wf, "Cash on Delivery could not be selected. Please complete checkout yourself.")

        live = await adapter.inspect_checkout(cctx, ctx.task_id)
        live.cart_id, live.version = summary.cart_id, summary.version + 1
        for _ in range(MAX_APPROVAL_ROUNDS):
            if not live.is_verified or live.final_total is None:
                raise CommerceError("COMMERCE_CHECKOUT_UNVERIFIED", "The final total or address could not be read; not ordering.", status="BLOCKED")
            wf.summary.checkout = live
            approval = await self._request_purchase_approval(ctx, wf, live)
            status = await self._approvals.wait(approval.approval_id, ctx.cancel_event, timeout=ctx.approval_ttl_seconds + 10)
            if ctx.cancel_event.is_set() or status is None:
                raise CommerceError("USER_CANCELLED", "Stopped by you before ordering. The cart remains prepared.", status="BLOCKED")
            await ctx.tasks.transition(ctx.task_id, TaskState.EXECUTING, reason="Purchase decision received")
            if status == ApprovalStatus.REJECTED:
                wf.summary.order = OrderState(task_id=wf.task_id, status=OrderStatus.REJECTED, approval_id=approval.approval_id,
                                              checkout_id=live.checkout_id, message="You rejected the purchase. No order was placed; the cart is still prepared.")
                self._touch(wf, WorkflowStatus.CART_READY, wf.summary.order.message)
                await self._emit(ctx, E.COMMERCE_PURCHASE_REJECTED, PurchaseStatusPayload(
                    platform=wf.binding.platform, status="REJECTED", message=wf.summary.order.message, approval_id=approval.approval_id))
                raise CommerceError("PURCHASE_REJECTED", wf.summary.order.message, status="BLOCKED")
            if status == ApprovalStatus.EXPIRED:
                raise CommerceError("PURCHASE_APPROVAL_EXPIRED", "The purchase approval expired. No order was placed.", status="BLOCKED")

            # Approved: re-load and re-read the live checkout; authorise only if NOTHING changed.
            await adapter.reload_page(cctx)  # type: ignore[attr-defined]
            recheck = await adapter.inspect_checkout(cctx, ctx.task_id)
            recheck.cart_id, recheck.version = live.cart_id, live.version + 1
            try:
                auth = self.purchase.authorize(task_id=ctx.task_id, approval=self._approval_service.get(approval.approval_id), live=recheck)
            except PurchaseBlockedError as exc:
                self.purchase.mark_approval_used(approval.approval_id)
                if exc.code == "PURCHASE_APPROVAL_STALE":
                    change = self.prices.compare("Order total", live.final_total, recheck.final_total)
                    message = (change.message() if change else "The checkout changed after your approval") + " Your previous approval is no longer valid."
                    wf.summary.price_changes.append(message)
                    await self._emit(ctx, E.COMMERCE_PRICE_CHANGED, PriceChangedPayload(
                        platform=wf.binding.platform, previous=live.final_total, current=recheck.final_total,
                        difference=(recheck.final_total - live.final_total) if (recheck.final_total is not None and live.final_total is not None) else None,
                        message=message, approval_invalidated=True))
                    live = recheck
                    continue
                raise CommerceError(exc.code, exc.message, status="BLOCKED") from exc

            if not await self._approval_service.consume(approval.approval_id):  # Phase 6: durable one-time use
                raise CommerceError("PURCHASE_APPROVAL_REUSED", "This purchase approval was already used. No order was placed.", status="BLOCKED")
            self.purchase.consume(auth)  # single use, recorded BEFORE the click: never submitted twice
            wf.summary.order = OrderState(task_id=wf.task_id, status=OrderStatus.SUBMISSION_PENDING, approval_id=approval.approval_id,
                                          checkout_id=recheck.checkout_id, message="Submitting the approved cash-on-delivery order once…")
            await self._emit(ctx, E.COMMERCE_ORDER_SUBMISSION_STARTED, PurchaseStatusPayload(
                platform=wf.binding.platform, status="SUBMITTING", message=wf.summary.order.message, approval_id=approval.approval_id,
                final_total=recheck.final_total))
            submission = await adapter.submit_cod_order(cctx, auth)
            state = order_state(ctx.task_id, submission, checkout_id=recheck.checkout_id, approval_id=approval.approval_id)
            wf.summary.order = state
            if state.status == OrderStatus.CONFIRMED:
                self._touch(wf, WorkflowStatus.ORDER_CONFIRMED, state.message)
                await self._emit(ctx, E.COMMERCE_ORDER_CONFIRMED, PurchaseStatusPayload(
                    platform=wf.binding.platform, status="CONFIRMED", message=state.message, approval_id=approval.approval_id,
                    final_total=recheck.final_total, order_reference=state.order_reference))
                return ctx.result(ActionExecutionStatus.SUCCEEDED, state.message, verified=True)
            self._touch(wf, WorkflowStatus.FAILED, state.message)
            await self._emit(ctx, E.COMMERCE_ORDER_STATUS_UNKNOWN, PurchaseStatusPayload(
                platform=wf.binding.platform, status="UNKNOWN", message=state.message, approval_id=approval.approval_id))
            return ctx.result(ActionExecutionStatus.FAILED, state.message, error_code="ORDER_SUBMISSION_UNKNOWN")
        raise CommerceError("PURCHASE_APPROVAL_STALE", "The checkout kept changing; no order was placed. Please review it again.", status="BLOCKED")

    async def _request_purchase_approval(self, ctx: ExecutionContext, wf: Workflow, summary: CheckoutSummary) -> Any:
        details = approval_details(summary)
        action_text, reason, impact = approval_text(summary, wf.binding.name)
        approval = await self._approvals.create(
            task_id=ctx.task_id, session_id=ctx.session_id, action_summary=action_text, domain=wf.binding.name,
            reason=reason, risk_level=RiskLevel.CRITICAL, estimated_impact=impact, ttl_seconds=ctx.approval_ttl_seconds,
            purchase=details,
        )
        wf.summary.order = OrderState(task_id=wf.task_id, status=OrderStatus.APPROVAL_PENDING, approval_id=approval.approval_id,
                                      checkout_id=summary.checkout_id, message="Waiting for your final purchase approval.")
        self._touch(wf, WorkflowStatus.APPROVAL_PENDING, wf.summary.order.message)
        await self._emit(ctx, E.COMMERCE_PURCHASE_APPROVAL_REQUIRED, PurchaseStatusPayload(
            platform=wf.binding.platform, status="APPROVAL_PENDING", message="Final purchase review is waiting for you.",
            approval_id=approval.approval_id, checkout_id=summary.checkout_id, final_total=summary.final_total))
        await ctx.tasks.transition(ctx.task_id, TaskState.WAITING_APPROVAL, reason="Waiting for your final purchase approval")
        step = ctx.current_step
        if step is not None:
            await self._emit(ctx, E.TASK_EXECUTION_PAUSED, ExecutionPausedPayload(step_id=step.step_id, reason="Final purchase review",
                                                                                   approval_id=approval.approval_id))
        return approval

    # ---------------------------------------------------------------- completion wording

    def completion_note(self, task_id: UUID) -> str | None:
        wf = self._workflows.get(task_id)
        order = wf.summary.order if wf else None
        if order is None:
            return None
        if order.status == OrderStatus.CONFIRMED:
            ref = f" Order reference: {order.order_reference}." if order.order_reference else ""
            return f"All steps ran. After your exact-order approval, one cash-on-delivery order was placed and the website shows it as confirmed.{ref}"
        if order.status == OrderStatus.PAYMENT_HANDOFF:
            return f"Cart and checkout are ready. {order.message} TaskPilot made no payment."
        return None

    def persona_kind(self, task_id: UUID) -> str | None:
        wf = self._workflows.get(task_id)
        order = wf.summary.order if wf else None
        if order is None:
            return None
        return {OrderStatus.CONFIRMED: "order_placed", OrderStatus.PAYMENT_HANDOFF: "payment_handoff"}.get(order.status)

    # ---------------------------------------------------------------- REST operations

    def summary(self, task_id: UUID, session_id: UUID | None = None) -> ShoppingSummary:
        wf = self._workflows.get(task_id)
        if wf is None:
            raise CommerceRequestError("COMMERCE_SUMMARY_NOT_FOUND", "This task has no shopping workflow yet.", 404)
        if session_id is not None and wf.session_id != session_id:
            raise CommerceRequestError("TASK_SESSION_MISMATCH", "This task belongs to a different session.", 403)
        return wf.summary

    def candidates_for(self, task_id: UUID) -> list[ProductCandidate]:
        wf = self._workflows.get(task_id)
        return list(wf.candidates.values()) if wf else []

    def order_status(self, task_id: UUID, session_id: UUID | None) -> OrderState:
        summary = self.summary(task_id, session_id)
        return summary.order or OrderState(task_id=task_id, status=OrderStatus.NOT_STARTED, message="No checkout has been started.")

    def cart(self, session_id: UUID) -> CartSnapshot:
        snapshot = self._session_carts.get(session_id)
        if snapshot is None:
            raise CommerceRequestError("COMMERCE_CART_UNVERIFIED", "No cart has been observed in this session's browser yet.", 404)
        return snapshot

    def _binding_for_session(self, session_id: UUID) -> SiteBinding:
        key = self._session_platform.get(session_id)
        binding = self.registry.binding(key) if key else None
        if binding is None:
            raise CommerceRequestError("COMMERCE_SESSION_REQUIRED", "No shopping site has been opened in this session.", 404)
        return binding

    async def _idle_session(self, session_id: UUID) -> Any:
        session = self._browser.peek_session(session_id)
        if session is None:
            raise CommerceRequestError("BROWSER_SESSION_NOT_FOUND", "No browser is running for this session.", 404)
        if session.lock.locked():
            raise CommerceRequestError("BROWSER_SESSION_BUSY", "A plan is running in this browser; try again when it finishes.", 409)
        return session

    async def refresh_cart(self, session_id: UUID) -> CartSnapshot:
        session = await self._idle_session(session_id)
        binding = self._binding_for_session(session_id)
        async with session.lock:
            cctx = self._cctx(session_id, None, binding)
            try:
                snapshot = await self.registry.adapter(binding.platform).inspect_cart(cctx)
            except CommerceError as exc:
                raise CommerceRequestError(exc.code, exc.message) from exc
        self._session_carts[session_id] = snapshot
        return snapshot

    async def update_quantity(self, session_id: UUID, item_id: UUID, quantity: int) -> CartSnapshot:
        current = self.cart(session_id)
        item = next((i for i in current.items if i.item_id == item_id), None)
        if item is None:
            raise CommerceRequestError("COMMERCE_PRODUCT_NOT_FOUND", "That item is not in the last observed cart; refresh the cart first.", 404)
        session = await self._idle_session(session_id)
        binding = self._binding_for_session(session_id)
        async with session.lock:
            cctx = self._cctx(session_id, None, binding)
            try:
                result = await self.registry.adapter(binding.platform).update_quantity(item, quantity, cctx)
            except CommerceError as exc:
                raise CommerceRequestError(exc.code, exc.message) from exc
        if not result.success or result.snapshot is None:
            raise CommerceRequestError(result.error_code or "COMMERCE_QUANTITY_MISMATCH", result.message)
        after = next((i for i in result.snapshot.items if i.product_name == item.product_name and i.pack_size == item.pack_size), None)
        if (after.quantity if after else 0) != quantity:
            raise CommerceRequestError("COMMERCE_QUANTITY_MISMATCH", "The cart did not end at the requested quantity.")
        self._session_carts[session_id] = result.snapshot
        for wf in self._workflows.values():  # any approval/checkout bound to the old cart is now stale
            if wf.session_id == session_id and wf.summary.checkout is not None:
                wf.summary.checkout.is_verified = False
                wf.summary.checkout.warnings.append("The cart changed after this review; review checkout again.")
        return result.snapshot

    async def checkout_review(self, task_id: UUID, session_id: UUID) -> CheckoutSummary:
        wf = self._workflows.get(task_id)
        if wf is None or wf.session_id != session_id:
            raise CommerceRequestError("COMMERCE_SUMMARY_NOT_FOUND" if wf is None else "TASK_SESSION_MISMATCH",
                                       "No shopping workflow for this task and session.", 404 if wf is None else 403)
        session = await self._idle_session(session_id)
        async with session.lock:
            cctx = self._cctx(session_id, task_id, wf.binding)
            try:
                return await self._review(cctx, wf)
            except CommerceError as exc:
                raise CommerceRequestError(exc.code, exc.message) from exc

    def checkout_summary(self, task_id: UUID, session_id: UUID | None) -> CheckoutSummary:
        summary = self.summary(task_id, session_id)
        if summary.checkout is None:
            raise CommerceRequestError("COMMERCE_CHECKOUT_UNVERIFIED", "No checkout review exists for this task yet.", 404)
        return summary.checkout


def _cart_extract(snapshot: CartSnapshot) -> dict[str, Any]:
    return {
        "source": "observed_dom", "item_count": snapshot.item_count,
        "items": [{"name": i.product_name[:120], "pack size": i.pack_size, "quantity": f"{i.quantity:g}",
                   "price": format_inr(i.line_total) if i.line_total is not None else None} for i in snapshot.items[:10]],
        "missing_fields": [],
    }
