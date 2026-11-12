"""Gmail adapter (Phase 5): compose -> fill -> save -> verify a DRAFT. Never sends.

The only clickable controls are Compose and "Save & close" (IntegrationPolicy refuses any
Send / Schedule send / Discard control for every purpose). Draft status is reported from what
the page shows: "Draft saved" indicator and the draft row in Drafts — never assumed.
"""

from __future__ import annotations

import re
from typing import Any

from app.integrations.adapter_base import IntegrationAdapterBase, wait_for
from app.integrations.base import IntegrationContext, IntegrationError
from app.integrations.policies import FieldKind, Purpose
from app.schemas.gmail import DraftStatus

COMPOSE_BUTTON = "div[gh='cm'], [role=button][aria-label='Compose']"
DIALOG = "div[role=dialog]"
TO_FIELD = "input[aria-label='To recipients'], input[aria-label='To'], textarea[name='to']"
SUBJECT = "input[name='subjectbox']"
BODY = "div[aria-label='Message Body'][contenteditable='true'], div[aria-label='Message Body']"
SAVE_CLOSE = "[aria-label='Save & close'], [data-tooltip='Save & close']"

RECIPIENTS_JS = r"""
() => {
  const box = [...document.querySelectorAll('div[role=dialog]')].pop();
  if (!box) return null;
  const chips = [...box.querySelectorAll('[email], [data-hovercard-id]')].map((c) => (c.getAttribute('email') || c.getAttribute('data-hovercard-id') || '').toLowerCase());
  return chips.filter((c) => c.includes('@'));
}
"""
DRAFT_STATE_JS = r"""
() => {
  const box = [...document.querySelectorAll('div[role=dialog]')].pop();
  const text = ((box ? box.innerText : '') + ' ' + ((document.querySelector('[role=alert]') || {}).innerText || '')).slice(0, 4000);
  if (/couldn.t save|could not save|error saving/i.test(text)) return 'FAILED';
  if (/draft saved|saved to drafts/i.test(text)) return 'SAVED';
  if (/saving/i.test(text)) return 'SAVING';
  return null;
}
"""
DRAFT_ROWS_JS = r"""
() => [...document.querySelectorAll('tr.zA')].map((r) => ({
  subject: ((r.querySelector('span.bog') || {}).innerText || '').trim(),
  draft: /\bdraft\b/i.test(r.innerText || ''),
}))
"""


class GmailAdapter(IntegrationAdapterBase):
    def drafts_url(self, ctx: IntegrationContext) -> str:
        return ctx.binding.base_url.split("#")[0]

    async def open(self, ctx: IntegrationContext) -> None:
        await self.goto(ctx, ctx.binding.base_url)
        page = await self.page(ctx)

        async def ready() -> Any:
            if await page.locator(COMPOSE_BUTTON).count():
                return True
            status = await self.access(ctx)
            return status.value if status.value != "READY" else None

        await wait_for(ready, ctx.timeout)
        await self.require_access(ctx, login_code="GMAIL_LOGIN_REQUIRED")
        if not await page.locator(COMPOSE_BUTTON).count():
            raise IntegrationError("GMAIL_UNAVAILABLE", "Gmail did not finish loading (no Compose button was found).")

    async def compose(self, ctx: IntegrationContext, recipients: list[str], subject: str, body: str) -> None:
        page = await self.page(ctx)
        await self.click(ctx, page.locator(COMPOSE_BUTTON).first, Purpose.GMAIL_COMPOSE, label="Compose")
        dialog = page.locator(DIALOG).last
        if await wait_for(lambda: _count(dialog.locator(SUBJECT)), ctx.timeout) is None:
            raise IntegrationError("GMAIL_COMPOSE_FAILED", "The compose window did not open.")
        to_text = ", ".join(recipients)
        to_field = dialog.locator(TO_FIELD).first
        await self.fill(ctx, to_field, to_text, FieldKind.RECIPIENTS)
        await self.press(ctx, to_field, "Tab", FieldKind.RECIPIENTS, to_text)
        shown = await wait_for(lambda: _recipients(ctx, len(recipients)), 5)
        if shown is None or sorted(shown) != sorted(r.lower() for r in recipients):
            raise IntegrationError("GMAIL_RECIPIENT_MISMATCH", "Gmail did not show exactly the requested recipients; the draft was not saved.")
        if not await self.fill(ctx, dialog.locator(SUBJECT).first, subject, FieldKind.SUBJECT):
            raise IntegrationError("GMAIL_COMPOSE_FAILED", "The subject could not be filled exactly.")
        if not await self.fill(ctx, dialog.locator(BODY).first, body, FieldKind.BODY, rich=True):
            raise IntegrationError("GMAIL_COMPOSE_FAILED", "The message body could not be filled exactly.")

    async def wait_saved(self, ctx: IntegrationContext, timeout: float) -> DraftStatus:
        async def settled() -> Any:
            state = await ctx.controller.evaluate(ctx.session_id, DRAFT_STATE_JS)
            return state if state in ("SAVED", "FAILED") else None

        state = await wait_for(settled, timeout)
        return {"SAVED": DraftStatus.DRAFT_SAVED, "FAILED": DraftStatus.DRAFT_SAVE_FAILED}.get(state or "", DraftStatus.DRAFT_SAVE_PENDING)

    async def save_and_close(self, ctx: IntegrationContext) -> DraftStatus:
        page = await self.page(ctx)
        close = page.locator(DIALOG).last.locator(SAVE_CLOSE).first
        if not await close.count():
            return DraftStatus.SAVE_STATUS_UNKNOWN
        await self.click(ctx, close, Purpose.GMAIL_SAVE_CLOSE, label="Save & close")

        async def toast() -> Any:
            text = await ctx.controller.evaluate(ctx.session_id, "() => ((document.querySelector('[role=alert]') || {}).innerText || '')")
            if re.search(r"couldn.t save|could not save", text or "", re.IGNORECASE):
                return "FAILED"
            return "SAVED" if re.search(r"draft saved", text or "", re.IGNORECASE) else None

        result = await wait_for(toast, 4)
        return {"SAVED": DraftStatus.DRAFT_SAVED, "FAILED": DraftStatus.DRAFT_SAVE_FAILED}.get(result or "", DraftStatus.SAVE_STATUS_UNKNOWN)

    async def verify_in_drafts(self, ctx: IntegrationContext, subject: str) -> bool:
        await self.goto(ctx, self.drafts_url(ctx))
        # URL normalisation drops fragments, so open the Drafts view with a fixed, same-document hash change.
        await ctx.controller.evaluate(ctx.session_id, "() => { location.hash = 'drafts'; }")

        async def found() -> Any:
            rows = await ctx.controller.evaluate(ctx.session_id, DRAFT_ROWS_JS)
            return any(r.get("subject") == subject for r in rows or []) or None

        return bool(await wait_for(found, ctx.timeout))


async def _count(locator: Any) -> int | None:
    return (await locator.count()) or None


async def _recipients(ctx: IntegrationContext, expected: int) -> list[str] | None:
    shown = await ctx.controller.evaluate(ctx.session_id, RECIPIENTS_JS)
    return shown if shown and len(shown) >= expected else None
