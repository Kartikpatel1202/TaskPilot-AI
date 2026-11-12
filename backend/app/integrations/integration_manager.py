"""IntegrationManager — runs YouTube / Gmail / Calendar / download plan steps (Phase 5).

Plan steps of the five integration action types are executed here (via the integration
action handler) on top of the Phase 3 execution engine. Everything reported comes from the
live page or the validated download; irreversible steps are gated (calendar: exact-event
approval; Gmail: drafts only — sending is never automated; downloads: allow-list + content
validation). One task runs at a time per browser session (execution queue + session lock).
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections import OrderedDict
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlsplit
from uuid import UUID, uuid4

from app.core.logging import get_logger
from app.execution.execution_result import ActionExecutionStatus, ActionResult
from app.integrations.base import IntegrationContext, IntegrationError
from app.integrations.calendar.adapter import CalendarAdapter
from app.integrations.calendar.event_review import approval_details, approval_text, build_review, event_from_action
from app.integrations.capability_registry import CapabilityError, CapabilityRegistry
from app.integrations.files.downloader import FileDownloader
from app.integrations.files.storage import FileRequestError, FileStore
from app.integrations.gmail.adapter import GmailAdapter
from app.integrations.policies import FieldKind, IntegrationPolicy
from app.integrations.registry import IntegrationRegistry
from app.integrations.youtube.adapter import YouTubeAdapter
from app.integrations.youtube.ranking import choose
from app.schemas.approval import ApprovalStatus, RiskLevel
from app.schemas.calendar import CalendarConflict, CalendarEventReview, CalendarEventStatus, ConflictCheckStatus
from app.schemas.common import utc_now
from app.schemas.execution import ExecutionPausedPayload, ExecutionResumedPayload
from app.schemas.files import DownloadAttempt, DownloadStatus
from app.schemas.gmail import DraftStatus, EmailDraftSummary
from app.schemas.integration import (
    CalendarCreateEventAction,
    ChoiceOption,
    DomainStatus,
    DomainStatusEntry,
    DomainType,
    FileDownloadAction,
    GmailCreateDraftAction,
    IntegrationEventPayload,
    PendingChoice,
    YouTubePlayAction,
    YouTubeSearchAction,
)
from app.schemas.task import TaskState
from app.schemas.telemetry import TelemetryEventType as E
from app.schemas.workflow import WorkflowState, WorkflowStatus, WorkflowStepStatus
from app.schemas.youtube import PlaybackState, YouTubeVideo
from app.workflow.result_handoff import MissingOutputError, file_output, resolve, youtube_output
from app.workflow.workflow_manager import WorkflowManager

if TYPE_CHECKING:
    from app.agent.plan_store import PlanStore
    from app.browser.controller import BrowserController
    from app.config import Settings
    from app.core.execution_events import ExecutionEvents
    from app.execution.approval_coordinator import ApprovalCoordinator
    from app.execution.execution_context import ExecutionContext
    from app.services.approval_service import ApprovalService
    from app.services.task_service import TaskService

logger = get_logger("integrations.manager")

SEND_BLOCKED_MESSAGE = "Haan bhai, main email ka draft prepare kar sakta hoon. Final Send tum Gmail se manually kar sakte ho."
_DOMAIN_LABEL = {DomainType.YOUTUBE: "YouTube", DomainType.GMAIL: "Gmail", DomainType.GOOGLE_CALENDAR: "Google Calendar",
                 DomainType.FILES: "Safe downloads"}
LINKS_JS = r"""
() => [...document.querySelectorAll('a[href]')].slice(0, 400).map((a) => ({ href: a.href, text: (a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 200) }))
"""


class IntegrationRequestError(Exception):
    """REST-level integration error (mapped to the standard API error format)."""

    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def mask_email(address: str) -> str:
    local, _, domain = str(address).partition("@")
    return (local[:1] + "•••@" + domain) if domain else "•••"


class IntegrationManager:
    def __init__(
        self, *, settings: Settings, registry: IntegrationRegistry, capabilities: CapabilityRegistry, controller: BrowserController,
        telemetry: ExecutionEvents, approvals: ApprovalCoordinator, approval_service: ApprovalService, store: PlanStore,
        tasks: TaskService, downloader: FileDownloader | None, files: FileStore | None,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.capabilities = capabilities
        self._controller = controller
        self._telemetry = telemetry
        self._approvals = approvals
        self._approval_service = approval_service
        self._plans = store
        self._tasks = tasks
        self.downloader = downloader
        self.files = files
        self.policy = IntegrationPolicy(max_recipients=settings.gmail_max_recipients, max_body=settings.gmail_max_draft_length)
        self.workflows = WorkflowManager(telemetry)
        self.youtube = YouTubeAdapter()
        self.gmail = GmailAdapter()
        self.calendar = CalendarAdapter()
        self._choice_futures: dict[UUID, asyncio.Future[str | None]] = {}
        self._observed: dict[tuple[UUID, DomainType], DomainStatusEntry] = {}
        self._drafts: OrderedDict[UUID, dict[str, Any]] = OrderedDict()
        self._started: dict[UUID, float] = {}
        self._workflow_slots = asyncio.Semaphore(settings.workflow_max_concurrency)
        # Phase 6 (set by the container): persistence, rate limiter, malware scanner.
        self.persistence: Any = None
        self.rate_limiter: Any = None
        self.scanner: Any = None
        self._holding: set[UUID] = set()

    # ---------------------------------------------------------------- plan step entry point

    async def run_step(self, ctx: ExecutionContext, action: Any) -> ActionResult:
        step = ctx.current_step
        assert step is not None
        state = self.workflows.ensure(ctx.plan)
        try:
            self.capabilities.require(action.type)  # runtime re-check: settings may have changed since planning
        except CapabilityError as exc:
            return ctx.result(ActionExecutionStatus.BLOCKED, exc.message, error_code=exc.code)
        if len(state.steps) > 1 and ctx.task_id not in self._holding:
            await self._workflow_slots.acquire()
            self._holding.add(ctx.task_id)
        loop = asyncio.get_running_loop()
        started = self._started.setdefault(ctx.task_id, loop.time())
        if loop.time() - started > self.settings.workflow_timeout_seconds:
            result = ctx.result(ActionExecutionStatus.FAILED, "The workflow ran out of time before this step.", error_code="WORKFLOW_TIMEOUT")
            await self.workflows.finished(state, step.step_id, WorkflowStepStatus.FAILED, result.message, result.error_code)
            return result
        await self.workflows.started(state, step.step_id)
        handler = {
            "youtube_search": self._youtube_search, "youtube_play": self._youtube_play, "gmail_create_draft": self._gmail_draft,
            "calendar_create_event": self._calendar_create, "file_download": self._file_download,
        }[action.type]
        try:
            result = await handler(ctx, state, action)
        except IntegrationError as exc:
            status = ActionExecutionStatus.BLOCKED if exc.status == "BLOCKED" else ActionExecutionStatus.FAILED
            result = ctx.result(status, exc.message, error_code=exc.code)
            domain = state.current_domain
            if domain is not None:
                if exc.code.endswith("LOGIN_REQUIRED"):
                    await self._observe(ctx, domain, DomainStatus.AUTHENTICATION_REQUIRED, exc.message)
                elif exc.code == "CAPTCHA_REQUIRED":
                    await self._observe(ctx, domain, DomainStatus.BLOCKED, exc.message)
                else:
                    await self._emit(ctx, E.INTEGRATION_ERROR, IntegrationEventPayload(domain=domain, message=exc.message[:500], code=exc.code,
                                                                                    step_id=step.step_id))
        except MissingOutputError as exc:
            result = ctx.result(ActionExecutionStatus.FAILED, f"A previous step did not produce the {exc.output_type} this step needs.",
                                error_code="WORKFLOW_INPUT_MISSING")
        wf_status = {
            ActionExecutionStatus.SUCCEEDED: WorkflowStepStatus.COMPLETED, ActionExecutionStatus.BLOCKED: WorkflowStepStatus.BLOCKED,
        }.get(result.status, WorkflowStepStatus.FAILED)
        await self.workflows.finished(state, step.step_id, wf_status, result.message, result.error_code)
        return result

    def _ictx(self, ctx: ExecutionContext, site_key: str, domain: DomainType, timeout: float) -> IntegrationContext:
        binding = self.registry.binding(site_key)
        if binding is None or binding.domain != domain:
            raise IntegrationError("INTEGRATION_SITE_UNSUPPORTED", "This site is not a supported integration.", status="BLOCKED")
        return IntegrationContext(session_id=ctx.session_id, task_id=ctx.task_id, controller=self._controller, policy=self.policy,
                                  telemetry=self._telemetry, binding=binding, timeout=timeout, cancel_event=ctx.cancel_event)

    async def _emit(self, ctx: Any, event: Any, payload: Any) -> None:
        await self._telemetry.emit(ctx.session_id, event, payload, task_id=ctx.task_id)

    async def _observe(self, ctx: Any, domain: DomainType, status: DomainStatus, message: str) -> None:
        self._observed[(ctx.session_id, domain)] = DomainStatusEntry(
            domain=domain, label=_DOMAIN_LABEL.get(domain, domain.value), status=status, message=message[:300],
            capabilities=self.capabilities.domain_capabilities(domain), observed_at=utc_now())
        if self.persistence is not None:
            await self.persistence.best_effort(self.persistence.sessions.save_integration_status(
                ctx.session_id, domain.value, status.value, message), "integration.status")
        event = {DomainStatus.CONNECTED: E.INTEGRATION_SESSION_READY, DomainStatus.AUTHENTICATION_REQUIRED: E.INTEGRATION_AUTHENTICATION_REQUIRED}.get(
            status, E.INTEGRATION_ERROR)
        await self._emit(ctx, event, IntegrationEventPayload(domain=domain, message=message[:500], status=status.value))

    # ---------------------------------------------------------------- user choices

    async def _ask_choice(self, ctx: ExecutionContext, state: WorkflowState, domain: DomainType, question: str,
                          options: list[ChoiceOption]) -> str | None:
        timeout = self.settings.execution_approval_ttl_seconds
        step = ctx.current_step
        assert step is not None
        choice = PendingChoice(choice_id=uuid4(), task_id=ctx.task_id, step_id=step.step_id, domain=domain, question=question[:300],
                               options=options, expires_at=utc_now() + timedelta(seconds=timeout))
        future: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
        self._choice_futures[choice.choice_id] = future
        state.pending_choice = choice
        wf_step = self.workflows.step(state, step.step_id)
        if wf_step is not None:
            wf_step.status = WorkflowStepStatus.WAITING_USER
        state.status = WorkflowStatus.WAITING_USER
        await ctx.tasks.transition(ctx.task_id, TaskState.WAITING_APPROVAL, reason="Waiting for you to choose")
        await self._emit(ctx, E.TASK_EXECUTION_PAUSED, ExecutionPausedPayload(step_id=step.step_id, reason=question[:900]))
        cancel = asyncio.ensure_future(ctx.cancel_event.wait())
        try:
            done, _ = await asyncio.wait({future, cancel}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            chosen = future.result() if future in done else None
        finally:
            cancel.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancel
            self._choice_futures.pop(choice.choice_id, None)
            state.pending_choice = None
        if ctx.cancel_event.is_set():
            raise IntegrationError("USER_CANCELLED", "Stopped by you while choosing.", status="BLOCKED")
        await ctx.tasks.transition(ctx.task_id, TaskState.EXECUTING, reason="Choice received" if chosen else "Nothing chosen")
        await self._emit(ctx, E.TASK_EXECUTION_RESUMED, ExecutionResumedPayload(step_id=step.step_id, message="Continuing with your choice."))
        if wf_step is not None:
            wf_step.status = WorkflowStepStatus.RUNNING
        state.status = WorkflowStatus.RUNNING
        return chosen if chosen in {o.option_id for o in options} else None

    def answer_choice(self, task_id: UUID, session_id: UUID, choice_id: UUID, option_id: str | None) -> None:
        state = self.workflows.get(task_id)
        if state is None:
            raise IntegrationRequestError("WORKFLOW_NOT_FOUND", "This task has no integration workflow.", 404)
        if state.session_id != session_id:
            raise IntegrationRequestError("TASK_SESSION_MISMATCH", "This task belongs to a different session.", 403)
        pending = state.pending_choice
        future = self._choice_futures.get(choice_id)
        if pending is None or pending.choice_id != choice_id or future is None or future.done():
            raise IntegrationRequestError("CHOICE_NOT_PENDING", "This choice is no longer pending.", 409)
        if option_id is not None and option_id not in {o.option_id for o in pending.options}:
            raise IntegrationRequestError("CHOICE_INVALID", "That option was not offered.", 422)
        future.set_result(option_id)

    # ---------------------------------------------------------------- YouTube

    async def _youtube_search(self, ctx: ExecutionContext, state: WorkflowState, action: YouTubeSearchAction) -> ActionResult:
        ictx = self._ictx(ctx, action.site_key, DomainType.YOUTUBE, self.settings.youtube_search_timeout_seconds)
        await self._emit(ctx, E.YOUTUBE_SEARCH_STARTED, IntegrationEventPayload(domain=DomainType.YOUTUBE, message=f"Searching YouTube for “{action.query[:80]}”."))
        limit = min(action.max_results, self.settings.youtube_max_search_results)
        videos = await self.youtube.search(ictx, action.query, limit, action.preferred_channel)
        state.youtube_results = videos
        await self._observe(ctx, DomainType.YOUTUBE, DomainStatus.CONNECTED, "YouTube results loaded.")
        await self._emit(ctx, E.YOUTUBE_SEARCH_COMPLETED, IntegrationEventPayload(domain=DomainType.YOUTUBE, message=f"{len(videos)} video(s) found.",
                                                                                  result_count=len(videos)))
        if not videos:
            return ctx.result(ActionExecutionStatus.FAILED, f"No YouTube videos were found for “{action.query[:80]}”.", error_code="YOUTUBE_NO_RESULTS")
        await self._emit(ctx, E.YOUTUBE_RESULTS_FOUND, IntegrationEventPayload(domain=DomainType.YOUTUBE, message="Results are ready.",
                                                                               result_count=len(videos)))
        data = {"results": [{"title": v.title, "channel": v.channel_name, "duration": v.duration} for v in videos[:10]]}
        if not action.select:
            return ctx.result(ActionExecutionStatus.SUCCEEDED, f"Found {len(videos)} YouTube video(s) for “{action.query[:60]}”.",
                              extracted_data=data, verified=True)
        selected, options = choose(videos)
        if selected is None:
            pending = ChoiceOption
            choice = await self._ask_choice(ctx, state, DomainType.YOUTUBE, "Several videos match. Which one should I use?", [
                pending(option_id=v.option_id, label=v.title[:300], detail=" · ".join(x for x in (v.channel_name, v.duration, v.views) if x)[:300])
                for v in options])
            selected = next((v for v in videos if v.option_id == choice), None)
            if selected is None:
                return ctx.result(ActionExecutionStatus.FAILED, "No video was chosen.", error_code="YOUTUBE_SELECTION_SKIPPED")
        state.youtube_selected = selected
        self.workflows.add_output(state, youtube_output(ctx.current_step.step_id, selected))  # type: ignore[union-attr]
        await self._emit(ctx, E.YOUTUBE_VIDEO_SELECTED, IntegrationEventPayload(domain=DomainType.YOUTUBE, message=f"Selected “{selected.title[:120]}”."))
        data["selected"] = {"title": selected.title, "channel": selected.channel_name, "url": selected.video_url}
        return ctx.result(ActionExecutionStatus.SUCCEEDED, f"Selected “{selected.title[:120]}” from {len(videos)} result(s).", extracted_data=data,
                          verified=True)

    async def _youtube_play(self, ctx: ExecutionContext, state: WorkflowState, action: YouTubePlayAction) -> ActionResult:
        ictx = self._ictx(ctx, action.site_key, DomainType.YOUTUBE, self.settings.youtube_playback_timeout_seconds)
        if action.video_reference == "selected_from_search":
            video = state.youtube_selected
            if video is None:
                raise MissingOutputError("youtube.video_reference")
        else:
            vid = self.youtube.video_id_from(ictx, action.video_reference)
            if vid is None:
                raise IntegrationError("YOUTUBE_VIDEO_INVALID", "That is not a valid YouTube watch link.", status="BLOCKED")
            video = YouTubeVideo(option_id="v1", video_id=vid, title=f"YouTube video {vid}", video_url=self.youtube.watch_url(ictx, vid),
                                 relevance=1.0, observed_at=utc_now())
        playback = await self.youtube.play(ictx, video, self.settings.youtube_playback_timeout_seconds)
        state.youtube_playback = playback
        if state.youtube_selected is None:
            state.youtube_selected = video
        payload = IntegrationEventPayload(domain=DomainType.YOUTUBE, message=playback.message[:500], status=playback.state.value)
        if playback.state == PlaybackState.PLAYING:
            await self._emit(ctx, E.YOUTUBE_PLAYBACK_STARTED, payload)
            self.workflows.add_output(state, youtube_output(ctx.current_step.step_id, video))  # type: ignore[union-attr]
            return ctx.result(ActionExecutionStatus.SUCCEEDED, f"Playing “{video.title[:100]}” — verified: playback time is advancing.",
                              extracted_data={"title": video.title, "url": video.video_url, "state": playback.state.value}, verified=True)
        if playback.state == PlaybackState.PAUSED:
            await self._emit(ctx, E.YOUTUBE_PLAYBACK_PAUSED, payload)
            return ctx.result(ActionExecutionStatus.FAILED, playback.message, error_code="YOUTUBE_PLAYBACK_PAUSED")
        await self._emit(ctx, E.YOUTUBE_PLAYBACK_ERROR, payload)
        if playback.state == PlaybackState.LOGIN_REQUIRED:
            await self._observe(ctx, DomainType.YOUTUBE, DomainStatus.AUTHENTICATION_REQUIRED, playback.message)
            return ctx.result(ActionExecutionStatus.BLOCKED, playback.message, error_code="YOUTUBE_LOGIN_REQUIRED")
        code = "YOUTUBE_PLAYBACK_BLOCKED" if playback.state == PlaybackState.PLAYBACK_BLOCKED else "YOUTUBE_PLAYBACK_UNVERIFIED"
        return ctx.result(ActionExecutionStatus.FAILED, playback.message, error_code=code)

    # ---------------------------------------------------------------- Gmail (drafts only)

    async def _gmail_draft(self, ctx: ExecutionContext, state: WorkflowState, action: GmailCreateDraftAction) -> ActionResult:
        ictx = self._ictx(ctx, action.site_key, DomainType.GMAIL, 15)
        recipients = [str(r) for r in action.recipient_emails]
        if action.cc_emails:
            raise IntegrationError("GMAIL_CC_UNSUPPORTED", "Adding CC recipients is not automated; please add CC yourself in the draft.", status="BLOCKED")
        if len(recipients) > self.settings.gmail_max_recipients:
            raise IntegrationError("GMAIL_RECIPIENT_INVALID", f"At most {self.settings.gmail_max_recipients} recipients are allowed.", status="BLOCKED")
        outputs = self.workflows.outputs(state)
        subject = resolve(action.subject, outputs)[:200]
        body = resolve(action.body, outputs)
        if len(body) > self.settings.gmail_max_draft_length:
            raise IntegrationError("TEXT_TOO_LONG", "The draft is longer than the allowed length.", status="BLOCKED")
        summary = EmailDraftSummary(status=DraftStatus.NOT_STARTED, recipients_masked=[mask_email(r) for r in recipients],
                                    recipient_count=len(recipients), cc_count=0, subject=subject, body_preview=body[:160],
                                    message="Preparing the draft…", send_blocked=action.send_requested)
        state.gmail_draft = summary
        self._drafts[ctx.task_id] = {"body": body, "subject": subject}
        while len(self._drafts) > 200:
            self._drafts.popitem(last=False)
        if action.send_requested:
            await self._emit(ctx, E.GMAIL_SEND_BLOCKED, IntegrationEventPayload(domain=DomainType.GMAIL, message=SEND_BLOCKED_MESSAGE,
                                                                               code="GMAIL_SEND_BLOCKED"))
        await self._emit(ctx, E.GMAIL_DRAFT_STARTED, IntegrationEventPayload(domain=DomainType.GMAIL, message="Opening Gmail to prepare a draft."))
        await self.gmail.open(ictx)
        await self._observe(ctx, DomainType.GMAIL, DomainStatus.CONNECTED, "Gmail is open in the browser session.")
        if ctx.reconciling and await self.gmail.verify_in_drafts(ictx, subject):
            # Phase 6 reconciliation: an interrupted earlier attempt already saved this draft — never duplicate it.
            summary.status, summary.verified, summary.saved_at = DraftStatus.DRAFT_SAVED, True, utc_now()
            summary.message = "The draft from the interrupted attempt is already in Gmail Drafts — not duplicated. The email has NOT been sent."
            await self._emit(ctx, E.GMAIL_DRAFT_VERIFIED, IntegrationEventPayload(domain=DomainType.GMAIL, message="Existing draft found (not sent).",
                                                                                 status=summary.status.value))
            self.workflows.add_output(state, _draft_output(ctx, subject))
            return ctx.result(ActionExecutionStatus.SUCCEEDED, summary.message,
                              extracted_data={"draft": {"subject": subject, "recipients": summary.recipients_masked, "sent": False}}, verified=True)
        await self.gmail.compose(ictx, recipients, subject, body)
        summary.status, summary.message = DraftStatus.DRAFT_COMPOSED, "Draft composed — saving…"
        await self._emit(ctx, E.GMAIL_DRAFT_COMPOSED, IntegrationEventPayload(domain=DomainType.GMAIL, message="Draft composed (not sent).",
                                                                             status=summary.status.value))
        summary.status = DraftStatus.DRAFT_SAVE_PENDING
        first = await self.gmail.wait_saved(ictx, 10)
        closed = await self.gmail.save_and_close(ictx)
        if DraftStatus.DRAFT_SAVED in (first, closed):
            await self._emit(ctx, E.GMAIL_DRAFT_SAVED, IntegrationEventPayload(domain=DomainType.GMAIL, message="Gmail shows “Draft saved”.",
                                                                              status=DraftStatus.DRAFT_SAVED.value))
        verified = await self.gmail.verify_in_drafts(ictx, subject)
        tail = " The email has NOT been sent." + (f" {SEND_BLOCKED_MESSAGE}" if action.send_requested else "")
        if verified:
            summary.status, summary.verified, summary.saved_at = DraftStatus.DRAFT_SAVED, True, utc_now()
            summary.message = "Draft saved and found in Gmail Drafts." + tail
            await self._emit(ctx, E.GMAIL_DRAFT_VERIFIED, IntegrationEventPayload(domain=DomainType.GMAIL, message="Draft found in Drafts (not sent).",
                                                                                 status=summary.status.value))
            self.workflows.add_output(state, _draft_output(ctx, subject))
            return ctx.result(ActionExecutionStatus.SUCCEEDED, summary.message,
                              extracted_data={"draft": {"subject": subject, "recipients": summary.recipients_masked, "sent": False}}, verified=True)
        failed = DraftStatus.DRAFT_SAVE_FAILED in (first, closed)
        summary.status = DraftStatus.DRAFT_SAVE_FAILED if failed else DraftStatus.SAVE_STATUS_UNKNOWN
        summary.message = ("Gmail reported that the draft could not be saved." if failed else
                           "The draft could not be found in Drafts, so its save status is unknown. Please check Gmail.") + tail
        await self._emit(ctx, E.GMAIL_DRAFT_FAILED, IntegrationEventPayload(domain=DomainType.GMAIL, message=summary.message[:500],
                                                                           status=summary.status.value))
        return ctx.result(ActionExecutionStatus.FAILED, summary.message,
                          error_code="GMAIL_DRAFT_SAVE_FAILED" if failed else "GMAIL_DRAFT_SAVE_UNKNOWN")

    # ---------------------------------------------------------------- Calendar

    async def _calendar_create(self, ctx: ExecutionContext, state: WorkflowState, action: CalendarCreateEventAction) -> ActionResult:
        ictx = self._ictx(ctx, action.site_key, DomainType.GOOGLE_CALENDAR, 15)
        event = event_from_action(action)
        review = build_review(event, action.assumptions)
        state.calendar = review
        await self._emit(ctx, E.CALENDAR_EVENT_PREPARED, IntegrationEventPayload(
            domain=DomainType.GOOGLE_CALENDAR, message=f"Event prepared: {review.date_label}, {review.time_label}.", status=review.status.value))
        if event.start_at <= utc_now():
            review.status = CalendarEventStatus.FAILED
            raise IntegrationError("CALENDAR_EVENT_IN_PAST", "The event start time has already passed; nothing was created.")
        if action.check_conflicts:
            seen = await self.calendar.list_day(ictx, event.start_at, event.timezone)
            await self._observe(ctx, DomainType.GOOGLE_CALENDAR, DomainStatus.CONNECTED, "Google Calendar is open in the browser session.")
            if seen is None:
                review.conflict_status = ConflictCheckStatus.UNAVAILABLE
            else:
                existing = await self._identical(event, seen)
                if existing:
                    review.status, review.verified_reference = CalendarEventStatus.ALREADY_EXISTS, existing
                    review.message = "An identical event is already on your calendar — no duplicate was created."
                    return ctx.result(ActionExecutionStatus.SUCCEEDED, review.message, extracted_data={"event": review.event.title}, verified=True)
                review.conflicts = _conflicts(event, seen)
                review.conflict_status = ConflictCheckStatus.CONFLICTS_FOUND if review.conflicts else ConflictCheckStatus.NO_CONFLICT_OBSERVED
                if review.conflicts:
                    await self._emit(ctx, E.CALENDAR_CONFLICT_DETECTED, IntegrationEventPayload(
                        domain=DomainType.GOOGLE_CALENDAR, message=f"{len(review.conflicts)} overlapping event(s) on that day.",
                        result_count=len(review.conflicts)))
        await self.calendar.open_form(ictx, event)
        await self._observe(ctx, DomainType.GOOGLE_CALENDAR, DomainStatus.CONNECTED, "Google Calendar is open in the browser session.")
        if not await self.calendar.form_matches(ictx, event):
            raise IntegrationError("CALENDAR_FORM_MISMATCH", "The calendar form did not show exactly the planned event; nothing was created.")
        # ---- exact-event approval
        action_text, reason, impact = approval_text(review, ictx.binding.name)
        approval = await self._approvals.create(
            task_id=ctx.task_id, session_id=ctx.session_id, action_summary=action_text, domain=ictx.binding.name, reason=reason,
            risk_level=RiskLevel.HIGH, estimated_impact=impact, ttl_seconds=ctx.approval_ttl_seconds, calendar=approval_details(review))
        review.status, review.approval_id = CalendarEventStatus.APPROVAL_PENDING, approval.approval_id
        state.pending_approval_id = approval.approval_id
        await self._emit(ctx, E.CALENDAR_APPROVAL_REQUIRED, IntegrationEventPayload(
            domain=DomainType.GOOGLE_CALENDAR, message="Please review the exact event.", approval_id=approval.approval_id, status=review.status.value))
        await ctx.tasks.transition(ctx.task_id, TaskState.WAITING_APPROVAL, reason="Waiting for your approval of the exact event")
        step = ctx.current_step
        assert step is not None
        await self._emit(ctx, E.TASK_EXECUTION_PAUSED, ExecutionPausedPayload(step_id=step.step_id, reason="Calendar event review",
                                                                              approval_id=approval.approval_id))
        decision = await self._approvals.wait(approval.approval_id, ctx.cancel_event, timeout=ctx.approval_ttl_seconds + 10)
        state.pending_approval_id = None
        if decision is None:
            review.status = CalendarEventStatus.REJECTED
            raise IntegrationError("USER_CANCELLED", "Stopped by you; no event was created.", status="BLOCKED")
        await self._emit(ctx, E.CALENDAR_APPROVAL_RESOLVED, IntegrationEventPayload(
            domain=DomainType.GOOGLE_CALENDAR, message=f"Approval {decision.value.lower()}.", status=decision.value, approval_id=approval.approval_id))
        if decision != ApprovalStatus.APPROVED:
            review.status = CalendarEventStatus.EXPIRED if decision == ApprovalStatus.EXPIRED else CalendarEventStatus.REJECTED
            review.message = "You rejected the event — nothing was created." if decision == ApprovalStatus.REJECTED else (
                "The approval expired — nothing was created.")
            code = "CALENDAR_EVENT_REJECTED" if decision == ApprovalStatus.REJECTED else "CALENDAR_APPROVAL_EXPIRED"
            return ctx.result(ActionExecutionStatus.BLOCKED, review.message, error_code=code)
        await ctx.tasks.transition(ctx.task_id, TaskState.EXECUTING, reason="Event approved")
        await self._emit(ctx, E.TASK_EXECUTION_RESUMED, ExecutionResumedPayload(step_id=step.step_id, message="Creating the approved event."))
        # ---- re-check: the approved hash, the live hash and the live form must all agree
        approved = self._approval_service.get(approval.approval_id)
        live = build_review(event, action.assumptions)
        approved_hash = approved.calendar.event_hash if approved.calendar else ""
        if not await self.calendar.form_matches(ictx, event):
            review.status = CalendarEventStatus.FAILED
            raise IntegrationError("CALENDAR_APPROVAL_STALE", "The event form changed after your approval; nothing was created.", status="BLOCKED")
        try:
            auth = self.policy.authorize_calendar(approval_id=approval.approval_id, task_id=ctx.task_id, approved=approved.status == ApprovalStatus.APPROVED,
                                                  approved_hash=approved_hash, live_hash=live.event_hash,
                                                  sends_invitations=bool(event.attendee_emails), window_seconds=ctx.approval_ttl_seconds)
        except ValueError as exc:
            review.status = CalendarEventStatus.FAILED
            raise IntegrationError(str(exc), "Your approval does not match this exact event any more; nothing was created.", status="BLOCKED") from exc
        if not await self._approval_service.consume(approval.approval_id):  # Phase 6: durable one-time use
            review.status = CalendarEventStatus.FAILED
            raise IntegrationError("CALENDAR_APPROVAL_REUSED", "This approval was already used; nothing was created.", status="BLOCKED")
        review.status = CalendarEventStatus.CREATING
        await self._emit(ctx, E.CALENDAR_EVENT_CREATION_STARTED, IntegrationEventPayload(domain=DomainType.GOOGLE_CALENDAR, message="Saving the approved event once."))
        await self.calendar.save(ictx, auth, live.event_hash)
        if await self.calendar.save_error(ictx):
            review.status = CalendarEventStatus.FAILED
            review.message = "Google Calendar reported that the event could not be saved."
            await self._emit(ctx, E.CALENDAR_EVENT_CREATION_FAILED, IntegrationEventPayload(domain=DomainType.GOOGLE_CALENDAR, message=review.message,
                                                                                            code="CALENDAR_EVENT_CREATION_FAILED"))
            return ctx.result(ActionExecutionStatus.FAILED, review.message, error_code="CALENDAR_EVENT_CREATION_FAILED")
        reference = None
        for _ in range(3):  # verification only re-reads the calendar; Save is never clicked again
            await asyncio.sleep(1.0)
            reference = await self.calendar.find(ictx, event)
            if reference:
                break
        review.observed_at = utc_now()
        if reference:
            review.status, review.verified_reference = CalendarEventStatus.CREATED, reference
            review.message = f"Event created and found on your calendar: {review.date_label}, {review.time_label}."
            await self._emit(ctx, E.CALENDAR_EVENT_CREATED, IntegrationEventPayload(domain=DomainType.GOOGLE_CALENDAR, message=review.message[:500],
                                                                                    status=review.status.value))
            self.workflows.add_output(state, _event_output(ctx, review))
            return ctx.result(ActionExecutionStatus.SUCCEEDED, review.message, extracted_data={"event": event.title, "when": review.time_label},
                              verified=True)
        review.status = CalendarEventStatus.UNKNOWN
        review.message = ("Save was clicked once, but the event could not be seen on your calendar. "
                          "Please check Google Calendar before trying again, to avoid a duplicate.")
        await self._emit(ctx, E.CALENDAR_EVENT_CREATION_FAILED, IntegrationEventPayload(domain=DomainType.GOOGLE_CALENDAR, message=review.message,
                                                                                        status=review.status.value, code="CALENDAR_EVENT_STATUS_UNKNOWN"))
        return ctx.result(ActionExecutionStatus.FAILED, review.message, error_code="CALENDAR_EVENT_STATUS_UNKNOWN")

    async def _identical(self, event: Any, seen: list[Any]) -> str | None:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(event.timezone)
        s, e = event.start_at.astimezone(tz), event.end_at.astimezone(tz)
        for item in seen:
            if item.title == event.title and item.start_min == s.hour * 60 + s.minute and item.end_min == e.hour * 60 + e.minute:
                return item.event_id or "visible"
        return None

    # ---------------------------------------------------------------- Files

    async def _file_download(self, ctx: ExecutionContext, state: WorkflowState, action: FileDownloadAction) -> ActionResult:
        if self.downloader is None:
            raise IntegrationError("FILE_DOWNLOAD_DISABLED", "Safe downloads are not enabled on this server.", status="BLOCKED")
        owner = ctx.user_id
        if self.rate_limiter is not None and not await self.rate_limiter.hit(
                f"dl:{owner or ctx.session_id}", self.settings.file_downloads_per_hour, 3600):
            raise IntegrationError("RATE_LIMITED", "Too many downloads this hour. Please try again later.", status="BLOCKED")
        if self.persistence is not None and owner is not None:
            count, used = await self.persistence.files.usage(owner)
            if count >= self.settings.file_max_count_per_user or used >= self.settings.file_storage_quota_mb_per_user * 1024 * 1024:
                raise IntegrationError("FILE_QUOTA_EXCEEDED", "Your download storage quota is full. Delete old files first.", status="BLOCKED")
        url = action.source_url
        ext = urlsplit(url).path.rsplit(".", 1)[-1].lower() if "." in urlsplit(url).path.rsplit("/", 1)[-1] else ""
        if ext not in self.settings.file_download_extension_list and not _looks_like_file(url):
            url = await self._find_link(ctx, state, action)
        await self._emit(ctx, E.FILE_DOWNLOAD_STARTED, IntegrationEventPayload(domain=DomainType.FILES, message=f"Downloading {action.file_description[:80]}…"))

        async def progress(received: int, total: int | None) -> None:
            await self._emit(ctx, E.FILE_DOWNLOAD_PROGRESS, IntegrationEventPayload(domain=DomainType.FILES, message="Downloading…", bytes_received=received))

        attempt = await self.downloader.download(url, session_id=ctx.session_id, task_id=ctx.task_id, on_progress=progress,
                                                 suggested_name=action.suggested_filename)
        state.downloads.append(attempt)
        if attempt.status == DownloadStatus.COMPLETED and attempt.file is not None:
            f = attempt.file
            scan = "SCAN_UNAVAILABLE"
            if self.scanner is not None and self.files is not None:
                stored = self.files.get(f.file_id, f.session_id)
                scan = await self.scanner.scan(stored.path)
                if scan == "INFECTED":
                    self.files.delete(f.file_id, f.session_id)
                    raise IntegrationError("FILE_MALWARE_DETECTED", "The malware scanner flagged this file; it was deleted.", status="BLOCKED")
            if self.persistence is not None:
                await self.persistence.best_effort(self.persistence.files.add(
                    f, user_id=ctx.user_id, storage_key=f"{f.session_id}/{f.stored_name}", scan_status=scan), "file.add")
            f.validation.append("malware scan: " + scan.replace("_", " ").lower())
            await self._emit(ctx, E.FILE_VALIDATION_COMPLETED, IntegrationEventPayload(domain=DomainType.FILES, message="Type, signature and size verified.",
                                                                                      file_id=f.file_id))
            await self._emit(ctx, E.FILE_DOWNLOAD_COMPLETED, IntegrationEventPayload(domain=DomainType.FILES, message=attempt.message[:500], file_id=f.file_id,
                                                                                    bytes_received=f.size_bytes, status=attempt.status.value))
            self.workflows.add_output(state, file_output(ctx.current_step.step_id, f))  # type: ignore[union-attr]
            return ctx.result(ActionExecutionStatus.SUCCEEDED, attempt.message, verified=True, extracted_data={"file": {
                "file_id": str(f.file_id), "name": f.original_name, "type": f.extension, "size_bytes": f.size_bytes, "sha256": f.sha256}})
        event = E.FILE_DOWNLOAD_BLOCKED if attempt.status == DownloadStatus.BLOCKED else E.FILE_DOWNLOAD_FAILED
        await self._emit(ctx, event, IntegrationEventPayload(domain=DomainType.FILES, message=attempt.message[:500], code=attempt.code,
                                                             status=attempt.status.value))
        status = ActionExecutionStatus.BLOCKED if attempt.status == DownloadStatus.BLOCKED else ActionExecutionStatus.FAILED
        return ctx.result(status, attempt.message, error_code=attempt.code or "FILE_DOWNLOAD_FAILED")

    async def _find_link(self, ctx: ExecutionContext, state: WorkflowState, action: FileDownloadAction) -> str:
        """Open the page in the session browser and pick the file link (the user chooses when unclear)."""
        try:
            await self._controller.navigate(ctx.session_id, action.source_url)
        except Exception as exc:  # noqa: BLE001
            message = getattr(exc, "message", "The page could not be opened.")
            raise IntegrationError(getattr(exc, "code", "NAVIGATION_FAILED"), message, status="BLOCKED") from exc
        links = await self._controller.evaluate(ctx.session_id, LINKS_JS) or []
        allowed = self.settings.file_download_extension_list
        candidates: list[tuple[str, str]] = []
        for link in links:
            href = link.get("href") or ""
            path = urlsplit(href).path
            ext = path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
            if ext in allowed and (action.expected_extension is None or ext == action.expected_extension.lower().lstrip(".")):
                candidates.append((urljoin(action.source_url, href), (link.get("text") or path.rsplit("/", 1)[-1])[:200]))
        if not candidates:
            raise IntegrationError("FILE_LINK_NOT_FOUND", "No downloadable file of an allowed type was found on that page.")
        words = {w for w in re.split(r"[^a-z0-9]+", action.file_description.lower()) if len(w) > 2}
        scored = sorted(candidates, key=lambda c: -sum(1 for w in words if w in (c[1] + " " + c[0]).lower()))
        best = sum(1 for w in words if w in (scored[0][1] + " " + scored[0][0]).lower())
        runner = sum(1 for w in words if w in (scored[1][1] + " " + scored[1][0]).lower()) if len(scored) > 1 else -1
        if best > 0 and best > runner:
            return scored[0][0]
        options = [ChoiceOption(option_id=f"f{i + 1}", label=text, detail=urlsplit(href).path.rsplit("/", 1)[-1][:120])
                   for i, (href, text) in enumerate(scored[:6])]
        chosen = await self._ask_choice(ctx, state, DomainType.FILES, "Which file should I download?", options)
        if chosen is None:
            raise IntegrationError("FILE_SELECTION_SKIPPED", "No file was chosen; nothing was downloaded.", status="BLOCKED")
        return scored[int(chosen[1:]) - 1][0]

    # ---------------------------------------------------------------- completion wording

    async def finalize(self, task_id: UUID, execution_status: str) -> WorkflowState | None:
        self._started.pop(task_id, None)
        if task_id in self._holding:
            self._holding.discard(task_id)
            self._workflow_slots.release()
        state = await self.workflows.finalize(task_id, execution_status)
        if state is not None and self.persistence is not None:
            await self.persistence.best_effort(self.persistence.workflows.save(state), "workflow.save")
        return state

    def completion_note(self, task_id: UUID) -> str | None:
        state = self.workflows.get(task_id)
        if state is None:
            return None
        parts: list[str] = []
        if state.youtube_playback is not None and state.youtube_playback.state == PlaybackState.PLAYING and state.youtube_selected:
            parts.append(f"Playing “{state.youtube_selected.title[:80]}” (verified).")
        elif state.youtube_selected is not None:
            parts.append(f"Selected video: “{state.youtube_selected.title[:80]}”.")
        if state.gmail_draft is not None and state.gmail_draft.verified:
            parts.append("Gmail draft saved and found in Drafts — NOT sent.")
        if state.calendar is not None and state.calendar.status == CalendarEventStatus.CREATED:
            parts.append(f"Calendar event created after your approval ({state.calendar.date_label}, {state.calendar.time_label}).")
        elif state.calendar is not None and state.calendar.status == CalendarEventStatus.ALREADY_EXISTS:
            parts.append("The event already existed; no duplicate was created.")
        done = [d for d in state.downloads if d.status == DownloadStatus.COMPLETED and d.file]
        if done:
            parts.append("Downloaded: " + ", ".join(d.file.original_name for d in done if d.file) + " (validated, never opened).")
        head = f"All {len(state.steps)} step(s) finished and were verified." if len(state.steps) > 1 else "Done and verified."
        return " ".join([head, *parts])[:1000]

    def partial_note(self, task_id: UUID) -> str | None:
        state = self.workflows.get(task_id)
        if state is None or len(state.steps) < 2:
            return None
        return "Partial result: " + self.workflows.result_text(state)

    def persona_kind(self, task_id: UUID, status: str) -> str | None:
        state = self.workflows.get(task_id)
        if state is None:
            return None
        if status != "COMPLETED":
            done = any(s.status == WorkflowStepStatus.COMPLETED for s in state.steps)
            return "workflow_partial" if done and len(state.steps) > 1 else None
        if state.gmail_draft is not None and state.gmail_draft.verified and len(state.steps) == 1:
            return "draft_saved"
        if state.calendar is not None and state.calendar.status == CalendarEventStatus.CREATED and len(state.steps) == 1:
            return "event_created"
        return "integration_completed"

    # ---------------------------------------------------------------- REST helpers

    def _state_for(self, task_id: UUID, session_id: UUID | None) -> WorkflowState:
        state = self.workflows.get(task_id)
        if state is None:
            raise IntegrationRequestError("WORKFLOW_NOT_FOUND", "This task has not run an integration workflow yet.", 404)
        if session_id is not None and state.session_id != session_id:
            raise IntegrationRequestError("TASK_SESSION_MISMATCH", "This task belongs to a different session.", 403)
        return state

    def _plan_for(self, task_id: UUID, session_id: UUID | None) -> Any:
        record = self._plans.get(task_id)
        if record is None or record.plan is None:
            raise IntegrationRequestError("PLAN_NOT_FOUND", "No plan exists for this task.", 404)
        if session_id is not None and record.session_id != session_id:
            raise IntegrationRequestError("TASK_SESSION_MISMATCH", "This task belongs to a different session.", 403)
        return record

    async def stored_workflow(self, task_id: UUID, session_id: UUID | None) -> WorkflowState | None:
        if self.persistence is None:
            return None
        state = await self.persistence.workflows.get(task_id)
        if state is not None and session_id is not None and state.session_id != session_id:
            raise IntegrationRequestError("TASK_SESSION_MISMATCH", "This task belongs to a different session.", 403)
        return state

    def workflow(self, task_id: UUID, session_id: UUID | None) -> WorkflowState:
        state = self.workflows.get(task_id)
        if state is not None:
            return self._state_for(task_id, session_id)
        record = self._plan_for(task_id, session_id)
        planned = self.workflows.preview(record.plan)  # planned view (nothing has run; not stored)
        if not planned.steps:
            raise IntegrationRequestError("WORKFLOW_NOT_FOUND", "This task has no integration workflow.", 404)
        return planned

    def youtube_results(self, task_id: UUID, session_id: UUID | None) -> dict[str, Any]:
        state = self._state_for(task_id, session_id)
        return {"results": state.youtube_results, "selected": state.youtube_selected, "playback": state.youtube_playback,
                "pending_choice": state.pending_choice}

    def gmail_draft(self, task_id: UUID, session_id: UUID | None) -> dict[str, Any]:
        state = self.workflows.get(task_id)
        if state is not None and state.gmail_draft is not None:
            self._state_for(task_id, session_id)
            body = self._drafts.get(task_id, {}).get("body")
            return {"draft": state.gmail_draft, "body": body, "editable": False}
        record = self._plan_for(task_id, session_id)
        action = next((s.action for s in record.plan.steps if s.action.type == "gmail_create_draft"), None)
        if action is None:
            raise IntegrationRequestError("DRAFT_NOT_FOUND", "This task has no email draft.", 404)
        draft = EmailDraftSummary(status=DraftStatus.NOT_STARTED, recipients_masked=[mask_email(str(r)) for r in action.recipient_emails],
                                  recipient_count=len(action.recipient_emails), cc_count=len(action.cc_emails), subject=action.subject,
                                  body_preview=action.body[:160], message="Planned draft — nothing has been written to Gmail yet.",
                                  send_blocked=action.send_requested)
        return {"draft": draft, "body": action.body, "editable": True, "recipients": [str(r) for r in action.recipient_emails]}

    async def update_draft(self, task_id: UUID, session_id: UUID, subject: str, body: str) -> dict[str, Any]:
        record = self._plan_for(task_id, session_id)
        task = await self._tasks.get_task(task_id)
        if task.state != TaskState.PLANNED or self.workflows.get(task_id) is not None:
            raise IntegrationRequestError("DRAFT_NOT_EDITABLE", "The draft can only be edited before the plan runs.", 409)
        decision = self.policy.check_fill(FieldKind.BODY, body)
        if decision.allowed:
            decision = self.policy.check_fill(FieldKind.SUBJECT, subject)
        if not decision.allowed:
            raise IntegrationRequestError(decision.code or "VALIDATION_ERROR", decision.message or "The draft text is not allowed.", 422)
        steps = []
        found = False
        for s in record.plan.steps:
            if s.action.type == "gmail_create_draft":
                s = s.model_copy(update={"action": s.action.model_copy(update={"subject": subject.strip()[:200], "body": body})})
                found = True
            steps.append(s)
        if not found:
            raise IntegrationRequestError("DRAFT_NOT_FOUND", "This task has no email draft.", 404)
        record.plan = record.plan.model_copy(update={"steps": steps})
        if self.persistence is not None:
            await self.persistence.best_effort(self.persistence.plans.save(record.plan, user_id=None, command=None, clarifications=[]),
                                               "plan.edit")
        return self.gmail_draft(task_id, session_id)

    def calendar_review(self, task_id: UUID, session_id: UUID | None) -> CalendarEventReview:
        state = self.workflows.get(task_id)
        if state is not None and state.calendar is not None:
            self._state_for(task_id, session_id)
            return state.calendar
        record = self._plan_for(task_id, session_id)
        action = next((s.action for s in record.plan.steps if s.action.type == "calendar_create_event"), None)
        if action is None:
            raise IntegrationRequestError("CALENDAR_EVENT_NOT_FOUND", "This task has no calendar event.", 404)
        return build_review(event_from_action(action), action.assumptions)

    def statuses(self, session_id: UUID | None) -> list[DomainStatusEntry]:
        enabled = CapabilityRegistry.enabled_domains(self.settings)
        out: list[DomainStatusEntry] = []
        for domain in (DomainType.YOUTUBE, DomainType.GMAIL, DomainType.GOOGLE_CALENDAR, DomainType.FILES):
            caps = self.capabilities.domain_capabilities(domain)
            if domain not in enabled:
                out.append(DomainStatusEntry(domain=domain, label=_DOMAIN_LABEL[domain], status=DomainStatus.NOT_CONFIGURED,
                                             message="Disabled in server settings.", capabilities=caps))
                continue
            seen = self._observed.get((session_id, domain)) if session_id else None
            if seen is not None:
                out.append(seen)
                continue
            message = {DomainType.FILES: "Allow-listed file types only; files are never opened or executed."}.get(
                domain, "Not used in this session yet. Sign in yourself in the browser if the site asks.")
            out.append(DomainStatusEntry(domain=domain, label=_DOMAIN_LABEL[domain], status=DomainStatus.AVAILABLE, message=message,
                                         capabilities=caps))
        return out


# ---------------------------------------------------------------------- helpers


def _looks_like_file(url: str) -> bool:
    last = urlsplit(url).path.rsplit("/", 1)[-1]
    return "." in last and not last.lower().endswith((".html", ".htm", ".php", ".asp", ".aspx", ".jsp"))


def _conflicts(event: Any, seen: list[Any]) -> list[CalendarConflict]:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(event.timezone)
    s, e = event.start_at.astimezone(tz), event.end_at.astimezone(tz)
    s_min, e_min = s.hour * 60 + s.minute, e.hour * 60 + e.minute if e.date() == s.date() else 24 * 60
    out: list[CalendarConflict] = []
    for item in seen:
        if item.start_min < 0 or item.end_min < 0:
            continue
        end = item.end_min if item.end_min > item.start_min else 24 * 60
        if item.start_min < e_min and s_min < end:
            kind = "EXACT" if (item.start_min, end) == (s_min, e_min) else "PARTIAL"
            out.append(CalendarConflict(title=item.title[:200], start_label=item.start_label, end_label=item.end_label, kind=kind))
    return out[:10]


def _draft_output(ctx: Any, subject: str) -> Any:
    from app.schemas.workflow import WorkflowOutput

    return WorkflowOutput(type="gmail.draft_reference", step_id=ctx.current_step.step_id, data={"subject": subject[:200], "sent": "false"})


def _event_output(ctx: Any, review: CalendarEventReview) -> Any:
    from app.schemas.workflow import WorkflowOutput

    return WorkflowOutput(type="calendar.event_reference", step_id=ctx.current_step.step_id, data={
        "title": review.event.title[:200], "when": f"{review.date_label}, {review.time_label}"})


def file_request_error(exc: FileRequestError) -> IntegrationRequestError:
    return IntegrationRequestError(exc.code, exc.message, exc.status_code)


__all__ = ["IntegrationManager", "IntegrationRequestError", "SEND_BLOCKED_MESSAGE", "DownloadAttempt", "mask_email"]
