"""MutationMonitor: observation-only DOM change tracking with FIXED, trusted JavaScript.

Records bounded, debounced summaries of meaningful changes (controls added/removed/replaced, relevant
text changes, visibility changes, dialogs opening/closing). It never reads input values, never records
password fields and keeps at most `buffer_size` events. Model text is never executed.
"""

from __future__ import annotations

from typing import Any

_INSTALL_JS = r"""
(limit) => {
  if (window.__tpMon) { window.__tpMon.limit = limit; return true; }
  const mon = { events: [], limit, last: {} };
  const interactive = 'a,button,input,select,textarea,[role=button],[role=link],[role=dialog],[role=alertdialog],[role=menuitem],[role=tab]';
  const label = (el) => {
    if (!el || el.nodeType !== 1) return null;
    if (el.matches && el.matches('input[type=password]')) return null;   // never describe password fields
    const raw = el.getAttribute('aria-label') || (el.tagName === 'INPUT' ? (el.getAttribute('placeholder') || el.name || '') : el.innerText || '');
    return String(raw).replace(/\s+/g, ' ').trim().slice(0, 80);
  };
  const push = (kind, el) => {
    const role = (el.getAttribute && (el.getAttribute('role') || el.tagName.toLowerCase())) || 'node';
    const name = label(el);
    if (name === null) return;
    const key = kind + '|' + role + '|' + name;
    const now = Date.now();
    if (mon.last[key] && now - mon.last[key] < 250) return;           // debounce repeats
    mon.last[key] = now;
    mon.events.push({ kind, role, name, t: now });
    if (mon.events.length > mon.limit) mon.events.splice(0, mon.events.length - mon.limit);
  };
  const relevant = (n) => n && n.nodeType === 1 && (n.matches(interactive) || n.querySelector && n.querySelector(interactive));
  mon.obs = new MutationObserver((records) => {
    for (const r of records) {
      if (r.type === 'childList') {
        r.addedNodes.forEach((n) => { if (relevant(n)) push(n.matches('[role=dialog],[role=alertdialog],dialog') ? 'dialog_opened' : 'added', n.matches(interactive) ? n : n.querySelector(interactive)); });
        r.removedNodes.forEach((n) => { if (relevant(n)) push(n.matches('[role=dialog],[role=alertdialog],dialog') ? 'dialog_closed' : 'removed', n.matches(interactive) ? n : n.querySelector(interactive)); });
      } else if (r.type === 'attributes' && r.target.matches && r.target.matches(interactive)) {
        push(['hidden', 'style', 'class'].includes(r.attributeName) ? 'visibility_changed' : 'attribute_changed', r.target);
      } else if (r.type === 'characterData' && r.target.parentElement && r.target.parentElement.closest(interactive)) {
        push('text_changed', r.target.parentElement.closest(interactive));
      }
    }
  });
  mon.obs.observe(document.documentElement, { subtree: true, childList: true, characterData: true, attributes: true,
                                               attributeFilter: ['aria-label', 'disabled', 'hidden', 'style', 'class', 'aria-hidden'] });
  window.__tpMon = mon;
  return true;
}
"""
_DRAIN_JS = "() => { const m = window.__tpMon; if (!m) return []; const out = m.events.slice(); m.events = []; return out; }"
_STOP_JS = "() => { const m = window.__tpMon; if (m) { m.obs.disconnect(); delete window.__tpMon; } return true; }"
_QUIET_JS = "() => { const m = window.__tpMon; if (!m || !m.events.length) return 1e9; return Date.now() - m.events[m.events.length - 1].t; }"


class MutationMonitor:
    def __init__(self, buffer_size: int = 100) -> None:
        self.buffer_size = buffer_size

    async def start(self, page: Any) -> bool:
        try:
            return bool(await page.evaluate(_INSTALL_JS, self.buffer_size))
        except Exception:  # noqa: BLE001 - navigation in progress: monitoring is best effort
            return False

    async def drain(self, page: Any) -> list[dict[str, Any]]:
        try:
            events = await page.evaluate(_DRAIN_JS)
        except Exception:  # noqa: BLE001
            return []
        return [e for e in events if isinstance(e, dict)][-self.buffer_size:]

    async def wait_quiet(self, page: Any, quiet_ms: int = 300, timeout_ms: int = 3000) -> None:
        """Wait until no relevant mutation happened for `quiet_ms` (bounded by `timeout_ms`)."""
        waited = 0
        while waited < timeout_ms:
            try:
                since = await page.evaluate(_QUIET_JS)
            except Exception:  # noqa: BLE001
                return
            if since >= quiet_ms:
                return
            await page.wait_for_timeout(100)
            waited += 100

    async def stop(self, page: Any) -> None:
        try:
            await page.evaluate(_STOP_JS)
        except Exception:  # noqa: BLE001
            pass
