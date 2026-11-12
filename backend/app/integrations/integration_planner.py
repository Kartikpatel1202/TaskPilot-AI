"""Deterministic integration planning (Phase 5).

The LLM (or the offline mock) classifies the request and extracts entities; this trusted code
turns them into typed YouTube / Gmail / Calendar / download steps for validated sites. Missing
facts are never invented: no recipient -> ask; no date/time/duration -> ask; ambiguous AM/PM or
dd/mm -> ask. Calendar times are parsed here, in Python, with an injected "now" and IANA zones.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError
from pydantic import EmailStr

from app.agent.policies.approval_policy import apply_risk_and_approvals
from app.integrations.calendar.datetime_parser import parse_event_time
from app.integrations.domain_router import domain_of
from app.integrations.gmail.composer import body_for, subject_for
from app.integrations.registry import IntegrationRegistry
from app.schemas.approval import RiskLevel
from app.schemas.common import utc_now
from app.schemas.integration import (
    CalendarCreateEventAction,
    DomainType,
    FileDownloadAction,
    GmailCreateDraftAction,
    OutputType,
    YouTubePlayAction,
    YouTubeSearchAction,
)
from app.schemas.intent import IntentClassification, WorkflowStepEntity
from app.schemas.plan import ClarificationExchange, PlannedAction, PlanStatus, TaskPlan

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s<>\"')]+")
_EMAIL = TypeAdapter(EmailStr)
_WATCH = re.compile(r"^https://(www\.)?youtube\.com/watch\?v=[\w-]{6,20}$")


def _say(lang: str, en: str, hinglish: str, hi: str) -> str:
    return {"hinglish": hinglish, "hi": hi}.get(lang, en)


class Rejection(Exception):
    """A request this phase refuses outright (e.g. downloading YouTube videos)."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class Clarification(Exception):
    def __init__(self, question: str, missing: str) -> None:
        self.question = question
        self.missing = missing
        super().__init__(question)


class IntegrationPlanner:
    def __init__(self, settings: Any, registry: IntegrationRegistry, *, clock: Callable[[], datetime] | None = None) -> None:
        self.settings = settings
        self.registry = registry
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def build(
        self, *, task_id: UUID, session_id: UUID, classification: IntentClassification, steps: list[WorkflowStepEntity],
        command_text: str, provider: str, model: str, history: list[ClarificationExchange], clarification_text: str = "",
    ) -> TaskPlan:
        lang = classification.language
        multi = len(steps) > 1
        self._clar_text = clarification_text  # sync method: per-call scratch value
        planned: list[PlannedAction] = []
        assumptions: list[str] = []
        producers: dict[str, PlannedAction] = {}
        labels: list[str] = []
        try:
            if len(steps) > self.settings.workflow_max_steps:
                raise Clarification(_say(lang, "That is too many steps for one request — please split it.",
                                         "Bhai, ek request mein itne steps nahi — thoda tod do.", "एक अनुरोध में इतने स्टेप नहीं — कृपया इसे बाँटें।"), "steps")
            for entity in steps:
                domain = domain_of(entity)
                binding = self.registry.binding_for_website(entity.target_website, domain)
                if binding is None and domain != DomainType.FILES:
                    raise _disabled(domain)
                key = binding.key if binding else "files"
                if binding is not None and binding.is_fixture:
                    note = "LOCAL TEST FIXTURE site — not the real website."
                    if note not in assumptions:
                        assumptions.append(note)
                text = entity.text or command_text
                if domain == DomainType.YOUTUBE:
                    self._youtube(entity, key, planned, producers, labels, multi, steps, lang)
                elif domain == DomainType.GMAIL:
                    self._gmail(entity, key, planned, producers, labels, multi, text, lang, assumptions)
                elif domain == DomainType.GOOGLE_CALENDAR:
                    self._calendar(entity, key, planned, labels, multi, text, command_text, clarification_text, lang, assumptions)
                else:
                    self._download(entity, binding, planned, producers, labels, multi, text, lang)
        except Rejection as r:
            return TaskPlan(
                plan_id=uuid4(), task_id=task_id, session_id=session_id, status=PlanStatus.REJECTED, intent=classification.intent,
                summary="Request is outside supported or safe capabilities.", user_facing_message=r.message, language=lang,
                confidence=classification.confidence, clarification_history=list(history), provider=provider, model=model,
                is_mock=provider == "mock", created_at=utc_now(),
            )
        except Clarification as c:
            return TaskPlan(
                plan_id=uuid4(), task_id=task_id, session_id=session_id, status=PlanStatus.NEEDS_CLARIFICATION,
                intent=classification.intent, summary="More information is needed before planning.", user_facing_message=c.question,
                language=lang, target_website=classification.target_website, confidence=classification.confidence,
                clarification_question=c.question, missing_information=[c.missing], clarification_history=list(history),
                provider=provider, model=model, is_mock=provider == "mock", created_at=utc_now(),
            )
        ordered = apply_risk_and_approvals(planned)
        joined = "; ".join(labels)
        summary = (f"Multi-domain workflow: {joined}." if multi else joined.rstrip(".") + ".")[:300]
        msg = _say(lang, f"Got it! Plan: {joined}. Emails are only saved as drafts; calendar events need your approval first.",
                   f"Haan bhai! Plan ready: {joined}. Email sirf draft banega; calendar event tumhari approval ke baad hi banega.",
                   f"ठीक है! योजना: {joined}। ईमेल केवल ड्राफ़्ट बनेगा; कैलेंडर इवेंट आपकी मंज़ूरी के बाद ही बनेगा।")
        return TaskPlan(
            plan_id=uuid4(), task_id=task_id, session_id=session_id, status=PlanStatus.READY, intent=classification.intent,
            summary=summary, user_facing_message=msg[:2000], language=lang, target_website=classification.target_website,
            confidence=classification.confidence, assumptions=assumptions[:10], clarification_history=list(history), steps=ordered,
            requires_human_approval=any(s.requires_approval for s in ordered), provider=provider, model=model,
            is_mock=provider == "mock", created_at=utc_now(),
        )

    # ---------------------------------------------------------------- domains

    def _add(self, planned: list[PlannedAction], action: Any, description: str, outcome: str, deps: list[PlannedAction] | None = None) -> PlannedAction:
        step = PlannedAction(step_id=uuid4(), order=len(planned) + 1, action=action, description=description[:300],
                             expected_outcome=outcome[:300], risk_level=RiskLevel.LOW, depends_on=[d.step_id for d in deps or []])
        planned.append(step)
        return step

    def _youtube(self, e: WorkflowStepEntity, key: str, planned: list[PlannedAction], producers: dict[str, PlannedAction],
                 labels: list[str], multi: bool, steps: list[WorkflowStepEntity], lang: str) -> None:
        play = e.intent == "YOUTUBE_PLAYBACK"
        url = e.url if e.url and _WATCH.match(e.url) else None
        if play and url:
            step = self._add(planned, YouTubePlayAction(type="youtube_play", video_reference=url, site_key=key, continue_on_failure=multi),
                             "Open the video and verify that it is playing.", "The video is playing (playback time advances).")
            producers["youtube.video_reference"] = step
            labels.append("play the YouTube video")
            return
        query = (e.search_query or e.text or "").strip()
        if not query:
            raise Clarification(_say(lang, "What should I search for on YouTube?", "YouTube pe kya search karun, bhai?", "YouTube पर क्या खोजूँ?"), "search_query")
        later_needs = any(s.include_previous_output for s in steps[steps.index(e) + 1:])
        select = play or later_needs
        search = self._add(planned, YouTubeSearchAction(type="youtube_search", query=query[:500], max_results=self.settings.youtube_max_search_results,
                                                        select=select, site_key=key, continue_on_failure=multi),
                           f"Search YouTube for “{query[:80]}” and read the real results" + (" and pick the best match (you choose if unclear)." if select else "."),
                           "Matching videos are listed" + ("; one is selected." if select else "."))
        if select:
            producers["youtube.video_reference"] = search
        labels.append(f"search YouTube for “{query[:60]}”")
        if play:
            step = self._add(planned, YouTubePlayAction(type="youtube_play", video_reference="selected_from_search", site_key=key,
                                                        continue_on_failure=multi),
                             "Open the selected video and verify that it is playing.", "The video is playing (verified on the page).", deps=[search])
            producers["youtube.video_reference"] = step
            labels.append("play the chosen video")

    def _gmail(self, e: WorkflowStepEntity, key: str, planned: list[PlannedAction], producers: dict[str, PlannedAction], labels: list[str],
               multi: bool, text: str, lang: str, assumptions: list[str]) -> None:
        raw = [e.recipient] if e.recipient else (EMAIL_RE.findall(text) or EMAIL_RE.findall(self._clar_text))
        recipients: list[str] = []
        for r in raw:
            try:
                recipients.append(str(_EMAIL.validate_python((r or "").strip())))
            except ValidationError:
                continue
        if not recipients:
            raise Clarification(_say(lang, "What's the recipient's email address? I won't guess it.",
                                     "Bhai, kisko bhejna hai — unka email address bata do? Main andaaza nahi lagaunga.",
                                     "प्राप्तकर्ता का ईमेल पता क्या है? मैं अंदाज़ा नहीं लगाऊँगा।"), "recipient_email")
        recipients = list(dict.fromkeys(recipients))[: self.settings.gmail_max_recipients]
        outputs: list[OutputType] = []
        deps: list[PlannedAction] = []
        if e.include_previous_output:
            for kind in ("youtube.video_reference", "file.reference"):
                if kind in producers:
                    outputs.append(kind)  # type: ignore[arg-type]
                    deps.append(producers[kind])
        sending = e.intent == "EMAIL_SEND" or "send" in [a.lower() for a in e.requested_actions]
        topic = e.message_topic
        subject = subject_for(topic, outputs, e.subject)
        body = body_for(topic, outputs, lang)[: self.settings.gmail_max_draft_length]
        self._add(planned, GmailCreateDraftAction(type="gmail_create_draft", recipient_emails=recipients, subject=subject, body=body,
                                                  purpose=(topic or None) and topic[:200], insert_outputs=outputs, send_requested=sending,
                                                  site_key=key, continue_on_failure=multi),
                  f"Compose a Gmail draft to {', '.join(recipients)[:120]} and save it (NOT sent).",
                  "The draft is saved in Gmail Drafts and verified. Nothing is sent.", deps=deps)
        if sending:
            assumptions.append("Sending is never automated: TaskPilot saves a draft and you press Send yourself in Gmail.")
        if "[Your name]" in body:
            assumptions.append("The draft ends with a [Your name] placeholder — edit it before sending.")
        labels.append(f"save an email draft to {', '.join(recipients)[:80]} (not sent)")

    def _calendar(self, e: WorkflowStepEntity, key: str, planned: list[PlannedAction], labels: list[str], multi: bool, text: str,
                  command_text: str, clarification_text: str, lang: str, assumptions: list[str]) -> None:
        # A step's own clause (multi-domain) plus any clarification answers ("30 minutes", "PM").
        extra = clarification_text if text != command_text else ""
        source = " ".join(x for x in (text, e.datetime_text if e.datetime_text and e.datetime_text not in text else None, extra) if x)
        parsed = parse_event_time(source, now=self._clock(), default_tz=self.settings.calendar_default_timezone,
                                  default_duration=self.settings.calendar_default_duration_minutes, lang=lang)
        if not parsed.ok:
            raise Clarification(parsed.question or "When should the event be?", parsed.missing[0] if parsed.missing else "datetime")
        assert parsed.start and parsed.end
        attendees = list(dict.fromkeys(m.lower() for m in EMAIL_RE.findall(text)))[: self.settings.calendar_max_attendees]
        title = (e.subject or "").strip() or "Meeting"
        action = CalendarCreateEventAction(
            type="calendar_create_event", title=title[:200], start_at=parsed.start, end_at=parsed.end, timezone=parsed.timezone,
            description=(e.message_topic or None), attendee_emails=attendees, assumptions=parsed.assumptions[:5], site_key=key,
            continue_on_failure=multi,
        )
        when = f"{parsed.start.strftime('%a %d %b, %I:%M %p').replace(' 0', ' ')} ({parsed.duration_minutes} min, {parsed.timezone})"
        self._add(planned, action, f"Prepare “{title[:60]}” on {when}, check conflicts, ask your approval, then create it once.",
                  "The exact event exists on your calendar after your approval (verified).")
        assumptions.extend(a for a in parsed.assumptions if a not in assumptions)
        if attendees:
            assumptions.append(f"Google Calendar will email invitations to {len(attendees)} attendee(s) once you approve.")
        labels.append(f"create calendar event “{title[:50]}” after your approval")

    def _download(self, e: WorkflowStepEntity, binding: Any, planned: list[PlannedAction], producers: dict[str, PlannedAction],
                  labels: list[str], multi: bool, text: str, lang: str) -> None:
        url = e.url or next(iter(URL_RE.findall(text)), None) or next(iter(URL_RE.findall(self._clar_text)), None)
        site = (e.target_website or "").lower()
        host = (urlsplit(url).hostname or "").lower() if url else ""
        if "youtube" in site or "youtu.be" in site or host.endswith(("youtube.com", "youtu.be")):
            raise Rejection(_say(lang, "Sorry, I can't download YouTube videos (copyright / platform terms). I can search and play them for you instead.",
                                 "Sorry bhai, YouTube videos download nahi kar sakta (copyright / platform rules). Search karke chala zaroor sakta hoon.",
                                 "माफ़ कीजिए, मैं YouTube वीडियो डाउनलोड नहीं कर सकता (कॉपीराइट / प्लेटफ़ॉर्म नियम)। खोजकर चला ज़रूर सकता हूँ।"))
        if url is None and binding is not None and binding.domain == DomainType.FILES:
            url = binding.base_url
        if url is None:
            raise Clarification(_say(lang, "Please share the link of the file (or the page that has it).",
                                     "Bhai, file ka link (ya jis page pe file hai) bhej do.", "कृपया फ़ाइल (या जिस पेज पर वह है) का लिंक दें।"), "url")
        description = (e.search_query or e.text or "file").strip()[:200] or "file"
        ext = next((x for x in self.settings.file_download_extension_list if re.search(rf"\b{x}\b", description.lower())), None)
        step = self._add(planned, FileDownloadAction(type="file_download", source_url=url[:2048], file_description=description,
                                                     expected_extension=ext, site_key="files", continue_on_failure=multi),
                         f"Download {description[:80]} safely (allowed types only; validated; never opened or run).",
                         "The file is stored privately for this session with its SHA-256.")
        producers["file.reference"] = step
        labels.append(f"download {description[:50]}")


def _disabled(domain: DomainType) -> Clarification:
    name = {DomainType.YOUTUBE: "YouTube", DomainType.GMAIL: "Gmail", DomainType.GOOGLE_CALENDAR: "Google Calendar"}.get(domain, domain.value)
    return Clarification(f"{name} automation is not enabled on this server.", "integration_disabled")
