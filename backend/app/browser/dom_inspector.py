"""Bounded, privacy-preserving DOM inspection of real Playwright pages.

All page-side code below is fixed, trusted JavaScript shipped with TaskPilot; no
model output is ever evaluated. The inspector never reads input *values*, hidden
fields, cookies or storage, and tags each visible interactive element with a
`data-tp-id` attribute so the resolver can build a trusted fallback locator.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from app.browser.session import safe_url
from app.core.logging import redact_text
from app.schemas.browser import BrowserPageState, DOMElementInfo

if TYPE_CHECKING:
    from playwright.async_api import Page

MAX_SNAPSHOT_CHARS = 20_000
TP_ID = re.compile(r"^tp-\d{1,7}$")
# `- textbox "Password": secret` -> `- textbox "Password"` (values of every field are dropped)
_FIELD_VALUE = re.compile(r'^(\s*- (?:textbox|searchbox|combobox|spinbutton)(?: "[^"\n]*")?(?: \[[^\]\n]*\])?):.*$', re.MULTILINE)

_INTERACTABLES_JS = r"""
(maxElements) => {
  const SENS = /(password|passwd|passcode|\botp\b|one[-_ ]?time|\bpin\b|cvv|cvc|card[-_ ]?number|cardnumber|cc-|security[-_ ]?code|\bupi\b|ifsc|account[-_ ]?number|aadhaar|\bpan\b)/i;
  const clean = (t, n = 160) => { const s = (t || '').replace(/\s+/g, ' ').trim(); return s ? s.slice(0, n) : null; };
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || parseFloat(s.opacity) === 0) return false;
    return !el.closest('[hidden],[aria-hidden="true"]');
  };
  const role = (el) => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit.toLowerCase().split(/\s+/)[0];
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'button' || tag === 'summary') return 'button';
    if (tag === 'a' && el.hasAttribute('href')) return 'link';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      if (['button', 'submit', 'reset', 'image'].includes(type)) return 'button';
      if (type === 'checkbox') return 'checkbox';
      if (type === 'radio') return 'radio';
      if (type === 'search') return 'searchbox';
      if (['', 'text', 'email', 'tel', 'url', 'number', 'password'].includes(type)) return 'textbox';
      return type;
    }
    if (el.isContentEditable) return 'textbox';
    return null;
  };
  const labelText = (el) => {
    if (el.labels && el.labels.length) return clean([...el.labels].map((l) => l.innerText).join(' '));
    const ids = el.getAttribute('aria-labelledby');
    if (ids) return clean(ids.split(/\s+/).map((id) => (document.getElementById(id) || {}).innerText || '').join(' '));
    return null;
  };
  const contextText = (el) => {
    let node = el.parentElement;
    for (let i = 0; i < 5 && node && node !== document.body; i++) {
      const t = node.innerText || '';
      if (t.length > 15) return clean(t, 240);
      node = node.parentElement;
    }
    return null;
  };
  const ROLES = ['button', 'link', 'textbox', 'searchbox', 'combobox', 'checkbox', 'radio', 'tab', 'menuitem', 'option', 'switch', 'spinbutton'];
  const els = document.querySelectorAll('input:not([type=hidden]),textarea,select,button,a[href],[role],[contenteditable="true"],summary');
  const out = [];
  let counter = window.__tpCounter || 0;
  for (const el of els) {
    if (out.length >= maxElements) break;
    const r = role(el);
    if (!(ROLES.includes(r) || el.isContentEditable)) continue;
    if (!visible(el)) continue;
    if (!el.dataset.tpId) { counter += 1; el.dataset.tpId = 'tp-' + counter; }
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase() || null;
    const aria = clean(el.getAttribute('aria-label'));
    const ph = clean(el.getAttribute('placeholder'));
    const lab = labelText(el);
    const isField = tag === 'input' || tag === 'textarea' || tag === 'select';
    const editable = (tag === 'input' && !['button', 'submit', 'reset', 'image', 'checkbox', 'radio', 'file', 'range', 'color'].includes(type || 'text'))
      || tag === 'textarea' || el.isContentEditable;
    const auto = el.getAttribute('autocomplete') || '';
    const attrs = [type, el.getAttribute('name'), el.id, auto, aria, ph, lab].join(' ');
    const sensitive = type === 'password' || /one-time-code|cc-|current-password|new-password/.test(auto) || (isField && SENS.test(attrs));
    const text = isField ? null : clean(el.innerText || el.textContent);
    const buttonValue = tag === 'input' && ['button', 'submit', 'reset'].includes(type) ? clean(el.value) : null;
    const name = aria || lab || buttonValue || text || ph || clean(el.getAttribute('title')) || clean(el.getAttribute('alt'));
    out.push({
      element_id: el.dataset.tpId, tag_name: tag, role: r, accessible_name: name, text_content: text,
      placeholder: ph, aria_label: aria, label: lab, input_type: type, context_text: contextText(el),
      is_visible: true, is_enabled: !(el.disabled || el.getAttribute('aria-disabled') === 'true'),
      is_interactive: true, is_editable: editable && !el.readOnly && !el.disabled, is_sensitive: sensitive,
    });
  }
  window.__tpCounter = counter;
  return out;
}
"""

_SUMMARY_JS = r"""
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const q = (sel) => [...document.querySelectorAll(sel)].filter(vis);
  const OTP = /(\botp\b|one[-_ ]?time|verification code|verify code)/i;
  const password = q('input[type=password]').length > 0;
  const otp = q('input').some((i) => (i.getAttribute('autocomplete') || '') === 'one-time-code' ||
      OTP.test([i.name, i.id, i.getAttribute('placeholder'), i.getAttribute('aria-label')].join(' ')));
  const headings = q('h1,h2,h3').slice(0, 8).map((h) => (h.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 120)).filter(Boolean);
  const interactive = q('a[href],button,input:not([type=hidden]),select,textarea,[role=button],[role=link]').length;
  const dialog = q('[role=dialog],dialog[open],[aria-modal="true"]').length > 0;
  return { password, otp, headings, interactive, dialog, path: location.pathname };
}
"""

_REGION_JS = r"""
([tokens, maxItems]) => {
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && !el.closest('[hidden],[aria-hidden="true"]'); };
  const norm = (t) => (t || '').toLowerCase();
  const describe = (el) => {
    const heading = el.querySelector('h1,h2,h3,h4,[role=heading]');
    return norm([el.getAttribute('aria-label'), el.id, el.getAttribute('data-testid'), heading ? heading.innerText : ''].join(' '));
  };
  const containers = [...document.querySelectorAll('main,section,article,ul,ol,table,[role=list],[role=region],[role=main],[data-testid],div[id]')].filter(vis);
  let best = null, bestScore = 0;
  for (const c of containers) {
    const label = describe(c);
    const score = tokens.reduce((acc, t) => acc + (label.includes(t) ? 2 : 0), 0);
    if (score > bestScore || (score === bestScore && best && score > 0 && c.contains(best))) { best = c; bestScore = score; }
  }
  const container = best || document.querySelector('main') || document.body;
  let items = [...container.querySelectorAll('li,article,[role=listitem],tr,[data-product],[data-item]')].filter(vis);
  items = items.filter((el) => !items.some((other) => other !== el && el.contains(other)));
  // Treat the container itself as one item only if it actually matched the requested target;
  // otherwise "nothing found" is reported honestly (and the caller may wait for rendering).
  if (!items.length && best) items = [container];
  const out = items.slice(0, maxItems).map((el) => {
    if (el.querySelector('input[type=password]')) return { heading: null, lines: [] };
    const heading = el.querySelector('h1,h2,h3,h4,[role=heading],strong,[data-name]');
    const lines = (el.innerText || '').split('\n').map((l) => l.replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 12).map((l) => l.slice(0, 160));
    return { heading: heading ? (heading.innerText || '').trim().slice(0, 160) : null, lines };
  });
  return { container: (container.getAttribute('aria-label') || container.id || container.tagName.toLowerCase()).slice(0, 80), total: items.length, items: out };
}
"""


class DOMInspector:
    async def inspect_interactables(self, page: Page, max_elements: int = 150) -> list[DOMElementInfo]:
        raw: list[dict[str, Any]] = await page.evaluate(_INTERACTABLES_JS, max(1, min(max_elements, 400)))
        elements: list[DOMElementInfo] = []
        for item in raw:
            for key in ("accessible_name", "text_content", "placeholder", "aria_label", "label", "context_text"):
                if item.get(key):
                    item[key] = redact_text(str(item[key]))
            if not TP_ID.match(str(item.get("element_id") or "")):
                item["element_id"] = None
            elements.append(DOMElementInfo.model_validate(item))
        return elements

    async def get_accessible_snapshot(self, page: Page) -> dict[str, Any]:
        """Playwright ARIA snapshot (YAML), redacted and size-bounded. Never raw HTML."""
        text = await page.locator("body").aria_snapshot(timeout=5_000)
        # Playwright includes current field values (even passwords); TaskPilot never exposes them.
        text = _FIELD_VALUE.sub(r"\1", text)
        text = redact_text(text)
        truncated = len(text) > MAX_SNAPSHOT_CHARS
        return {"format": "aria-yaml", "snapshot": text[:MAX_SNAPSHOT_CHARS], "truncated": truncated}

    async def inspect_page_summary(self, page: Page) -> BrowserPageState:
        url = safe_url(page.url)
        try:
            title = (await page.title())[:200] or None
            data: dict[str, Any] = await page.evaluate(_SUMMARY_JS)
        except Exception:  # navigating / closed
            return BrowserPageState(url=url)
        path = str(data.get("path") or "").lower()
        auth_reason = None
        if data.get("password"):
            auth_reason = "A password field is shown."
        elif data.get("otp"):
            auth_reason = "A one-time-code (OTP) field is shown."
        elif re.search(r"/(login|signin|sign-in|auth|account/login)\b", path):
            auth_reason = "The site redirected to a sign-in page."
        from urllib.parse import urlsplit

        return BrowserPageState(
            url=url,
            domain=(urlsplit(url).hostname if url else None),
            title=title,
            headings=[redact_text(h) for h in data.get("headings", [])],
            interactive_count=int(data.get("interactive", 0)),
            has_password_field=bool(data.get("password")),
            auth_required=auth_reason is not None,
            auth_reason=auth_reason,
            dialog_open=bool(data.get("dialog")),
        )

    async def extract_region(self, page: Page, tokens: list[str], max_items: int = 10) -> dict[str, Any]:
        result: dict[str, Any] = await page.evaluate(_REGION_JS, [tokens[:12], max(1, min(max_items, 20))])
        for item in result.get("items", []):
            item["lines"] = [redact_text(line) for line in item.get("lines", [])]
            if item.get("heading"):
                item["heading"] = redact_text(item["heading"])
        return result
