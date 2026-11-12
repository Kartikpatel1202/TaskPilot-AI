"""Google Calendar adapter (Phase 5).

- Prefills the documented event template URL (no typing into the calendar),
- reads one day's visible events for an advisory conflict / duplicate check,
- re-reads the prefilled form and compares it with the approved event before Save,
- clicks Save only with a single-use authorization bound to the exact event hash,
- verifies the event on the calendar afterwards (UNKNOWN when it cannot be seen — never assumed).
Never deletes or modifies existing events.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from app.integrations.adapter_base import IntegrationAdapterBase, wait_for
from app.integrations.base import IntegrationContext, IntegrationError
from app.integrations.policies import CalendarAuthorization, Purpose
from app.schemas.calendar import CalendarEventRequest

EVENTS_JS = r"""
() => [...document.querySelectorAll('[data-eventid]')].map((e) => ({
  id: e.getAttribute('data-eventid'), label: (e.getAttribute('aria-label') || e.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 300),
}))
"""
FORM_JS = r"""
() => {
  const v = (sel) => { const el = document.querySelector(sel); return el ? (el.value !== undefined ? el.value : el.innerText).trim() : null; };
  return {
    title: v("input[aria-label='Title']"), start_date: v("input[aria-label='Start date']"), start_time: v("input[aria-label='Start time']"),
    end_time: v("input[aria-label='End time']"), end_date: v("input[aria-label='End date']"),
    guests: [...document.querySelectorAll('[data-email], [data-hovercard-id]')].map((g) => (g.getAttribute('data-email') || g.getAttribute('data-hovercard-id') || '').toLowerCase()).filter((g) => g.includes('@')),
    has_save: !!document.querySelector("#xSaveBu, [aria-label='Save']"),
  };
}
"""
_LABEL = re.compile(
    r"^(\d{1,2}(?::\d{2})?\s*[ap]m)\s*(?:to|–|-)\s*(\d{1,2}(?::\d{2})?\s*[ap]m),\s*([^,]+)", re.IGNORECASE)


@dataclass
class SeenEvent:
    event_id: str
    title: str
    start_label: str
    end_label: str
    start_min: int
    end_min: int


def _minutes(label: str) -> int:
    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*([ap])m", label.strip(), re.IGNORECASE)
    if not m:
        return -1
    h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0)
    return h * 60 + int(m.group(2) or 0)


def clock(dt: datetime) -> str:
    """'3:00pm' — the format the calendar form and fixture show."""
    return dt.strftime("%I:%M%p").lstrip("0").lower()


class CalendarAdapter(IntegrationAdapterBase):
    def edit_url(self, ctx: IntegrationContext, event: CalendarEventRequest) -> str:
        fmt = "%Y%m%dT%H%M%SZ"
        params: dict[str, str] = {
            "text": event.title,
            "dates": f"{event.start_at.astimezone(timezone.utc).strftime(fmt)}/{event.end_at.astimezone(timezone.utc).strftime(fmt)}",
            "ctz": event.timezone,
        }
        if event.description:
            params["details"] = event.description
        if event.location:
            params["location"] = event.location
        if event.attendee_emails:
            params["add"] = ",".join(str(a) for a in event.attendee_emails)
        query = urlencode(params)
        if ctx.binding.is_fixture:
            return ctx.binding.url(f"eventedit.html?{query}")
        return f"https://calendar.google.com/calendar/r/eventedit?{query}"

    def day_url(self, ctx: IntegrationContext, start: datetime, tz: str) -> str:
        local = start.astimezone(ZoneInfo(tz))
        if ctx.binding.is_fixture:
            return ctx.binding.url(f"day.html?{urlencode({'date': local.strftime('%Y-%m-%d'), 'ctz': tz})}")
        return f"https://calendar.google.com/calendar/r/day/{local.year}/{local.month}/{local.day}"

    async def list_day(self, ctx: IntegrationContext, start: datetime, tz: str) -> list[SeenEvent] | None:
        """Visible events of that day, or None when the calendar could not be read."""
        await self.goto(ctx, self.day_url(ctx, start, tz))
        await self.require_access(ctx, login_code="CALENDAR_LOGIN_REQUIRED")
        page = await self.page(ctx)

        async def loaded() -> Any:
            return await page.locator("[role=grid], [data-eventid]").count() or None

        if await wait_for(loaded, ctx.timeout) is None:
            return None
        raw = await ctx.controller.evaluate(ctx.session_id, EVENTS_JS) or []
        seen: list[SeenEvent] = []
        for item in raw:
            m = _LABEL.match(item.get("label") or "")
            if not m:
                continue
            seen.append(SeenEvent(item.get("id") or "", m.group(3).strip(), m.group(1), m.group(2), _minutes(m.group(1)), _minutes(m.group(2))))
        if raw and not seen:
            return None  # events are there but unreadable: conflicts UNKNOWN, never "free"
        return seen

    async def open_form(self, ctx: IntegrationContext, event: CalendarEventRequest) -> None:
        await self.goto(ctx, self.edit_url(ctx, event))
        await self.require_access(ctx, login_code="CALENDAR_LOGIN_REQUIRED")

        async def ready() -> Any:
            form = await ctx.controller.evaluate(ctx.session_id, FORM_JS)
            return form if form.get("has_save") and form.get("title") is not None else None

        if await wait_for(ready, ctx.timeout) is None:
            await self.require_access(ctx, login_code="CALENDAR_LOGIN_REQUIRED")
            raise IntegrationError("CALENDAR_FORM_UNAVAILABLE", "The event form did not load.")

    async def form_matches(self, ctx: IntegrationContext, event: CalendarEventRequest) -> bool:
        """The prefilled form shows exactly the approved title, times and guests."""
        form = await ctx.controller.evaluate(ctx.session_id, FORM_JS)
        tz = ZoneInfo(event.timezone)
        start, end = event.start_at.astimezone(tz), event.end_at.astimezone(tz)
        expected_date = f"{start.strftime('%A, %B')} {start.day}"
        return (
            (form.get("title") or "") == event.title
            and (form.get("start_time") or "").lower() == clock(start)
            and (form.get("end_time") or "").lower() == clock(end)
            and (form.get("start_date") or "").startswith(expected_date)
            and sorted(form.get("guests") or []) == sorted(str(a).lower() for a in event.attendee_emails)
        )

    async def save(self, ctx: IntegrationContext, authorization: CalendarAuthorization, event_hash: str) -> None:
        page = await self.page(ctx)
        button = page.locator("#xSaveBu, button[aria-label='Save']").first
        await self.click(ctx, button, Purpose.CALENDAR_SAVE, label="Save", authorization=authorization, event_hash=event_hash, settle_ms=800)
        dialog = page.locator("[role=dialog]").last
        if await wait_for(lambda: _count(dialog.locator("button")), 3):
            want = "Send" if authorization.sends_invitations else "Don't send"
            target = dialog.locator("button", has_text=re.compile(rf"^\s*{re.escape(want)}\s*$", re.IGNORECASE)).first
            if not await target.count():
                raise IntegrationError("CALENDAR_INVITE_DIALOG", "The invitation dialog was not as expected; please finish it yourself.", status="BLOCKED")
            await self.click(ctx, target, Purpose.CALENDAR_INVITES, label=want, authorization=authorization)
            authorization.invite_answered = True

    async def save_error(self, ctx: IntegrationContext) -> bool:
        text = await ctx.controller.evaluate(ctx.session_id, "() => ((document.querySelector('[role=alert]') || {}).innerText || '')")
        return bool(re.search(r"couldn.t save|could not save|error", text or "", re.IGNORECASE))

    async def find(self, ctx: IntegrationContext, event: CalendarEventRequest) -> str | None:
        """The visible event id of an identical event (same title, start and end), if any."""
        seen = await self.list_day(ctx, event.start_at, event.timezone)
        if not seen:
            return None
        tz = ZoneInfo(event.timezone)
        start, end = event.start_at.astimezone(tz), event.end_at.astimezone(tz)
        s_min, e_min = start.hour * 60 + start.minute, end.hour * 60 + end.minute
        for item in seen:
            if item.title == event.title and item.start_min == s_min and item.end_min == e_min:
                return item.event_id or "visible"
        return None


async def _count(locator: Any) -> int | None:
    return (await locator.count()) or None
