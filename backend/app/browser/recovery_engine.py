"""Bounded recovery engine for click/type target resolution failures.

1. detect + classify (trusted signals) -> only SELECTOR_NOT_FOUND / DOM_CHANGED / ELEMENT_HIDDEN qualify;
2. wait for the DOM to settle (MutationMonitor) and re-inspect it from scratch;
3. compare the expected target with current candidates using relaxed, synonym-aware matching
   restricted to the same role group; accept ONLY a unique, clearly better candidate;
4. optionally ask the LLM to pick from the observed candidate names (validated, never executed);
5. otherwise stop with a clear failure — never a random click.

Recovery happens before anything is clicked or typed, so it can never repeat a mutation. The caller
still applies the runtime BrowserActionPolicy to the recovered element.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from app.agent.self_correction.evidence_builder import build_evidence
from app.agent.self_correction.failure_classifier import FailureType, classify
from app.agent.self_correction.recovery_policy import RecoveryPolicy, replacement_allowed
from app.agent.self_correction.replanner import Replanner
from app.browser.mutation_monitor import MutationMonitor
from app.browser.selector_resolver import ROLE_GROUPS, ResolvedTarget, significant, tokens
from app.core.logging import get_logger
from app.schemas.approval import RiskLevel
from app.schemas.browser import TargetDescription

logger = get_logger("browser.recovery")

# UI wording that commonly changes between site versions (same meaning, same risk).
UI_SYNONYMS: dict[str, set[str]] = {
    "show": {"show", "load", "view", "see", "display"},
    "more": {"more", "additional", "next"},
    "search": {"search", "find", "go", "lookup"},
    "close": {"close", "dismiss", "x", "done"},
    "next": {"next", "continue", "forward"},
    "back": {"back", "previous", "prev"},
    "open": {"open", "view", "show"},
    "menu": {"menu", "navigation", "nav"},
    "filter": {"filter", "filters", "refine"},
    "sort": {"sort", "order", "arrange"},
}
RELAXED_MIN = 0.67
UNIQUE_MARGIN = 0.2


def _expand(words: set[str]) -> list[set[str]]:
    return [UI_SYNONYMS.get(w, {w}) | {w} for w in words]


def relaxed_score(target_words: set[str], name: str | None) -> float:
    have = tokens(name)
    if not target_words or not have:
        return 0.0
    groups = _expand(target_words)
    return sum(1 for g in groups if g & have) / len(groups)


def _role_ok(hint: str | None, role: str | None) -> bool:
    if not hint:
        return True
    group = next((g for g in ROLE_GROUPS if hint.lower() in g), {hint.lower()})
    return (role or "").lower() in group


class RecoveryEngine:
    def __init__(self, *, policy: RecoveryPolicy, monitor: MutationMonitor, replanner: Replanner | None = None,
                 metrics: Any | None = None) -> None:
        self.policy = policy
        self.monitor = monitor
        self.replanner = replanner
        self.metrics = metrics

    async def recover(self, ctx: Any, target: TargetDescription, intent: str, error: Any, *,
                      step_risk: RiskLevel = RiskLevel.LOW) -> ResolvedTarget | None:
        failure = classify(getattr(error, "code", None), getattr(error, "message", str(error)))
        if not self.policy.may_recover(failure, 0):
            return None
        if self.metrics is not None:
            self.metrics.selector_recovery.inc()
        try:
            async with asyncio.timeout(self.policy.max_seconds):
                resolved = await self._attempts(ctx, target, intent, failure, step_risk)
        except asyncio.TimeoutError:
            resolved = None
        if resolved is not None and self.metrics is not None:
            self.metrics.selector_recovery_success.inc()
        return resolved

    async def _attempts(self, ctx: Any, target: TargetDescription, intent: str, failure: FailureType,
                        step_risk: RiskLevel) -> ResolvedTarget | None:
        page = await ctx.controller.page_for(ctx.session_id)
        await self.monitor.start(page)
        replans = 0
        try:
            for attempt in range(self.policy.max_attempts):
                await self.monitor.wait_quiet(page, quiet_ms=300, timeout_ms=1500 + 500 * attempt)
                elements = await ctx.controller.inspector.inspect_interactables(page)
                pool = [e for e in elements if e.element_id and e.is_visible and e.is_enabled and _role_ok(target.role_hint, e.role)
                        and (intent != "type" or e.is_editable) and not e.is_sensitive]
                wanted = significant(target.accessible_name, target.text_hint, target.description) or tokens(target.description)
                scored = sorted(((relaxed_score(wanted, e.accessible_name), e) for e in pool), key=lambda x: x[0], reverse=True)
                best = scored[0] if scored else None
                runner_up = scored[1][0] if len(scored) > 1 else 0.0
                if best and best[0] >= RELAXED_MIN and best[0] - runner_up >= UNIQUE_MARGIN \
                        and replacement_allowed(step_risk, best[1].accessible_name or ""):
                    logger.info("recovery.relabelled_target", extra={"role": best[1].role, "score": round(best[0], 2)})
                    return await self._accept(ctx, page, best[1], target, best[0], intent)
                if self.replanner is not None and replans < self.policy.max_replans:
                    replans += 1
                    evidence = build_evidence(failure_type=failure.value, description=target.description,
                                              expected=target.accessible_name or target.text_hint or target.description,
                                              url=page.url, title=await page.title(), elements=pool, events=await self.monitor.drain(page))
                    choice = await self.replanner.suggest(evidence)
                    matches = [e for e in pool if (e.accessible_name or "").strip() == choice] if choice else []
                    if len(matches) == 1 and replacement_allowed(step_risk, choice or ""):
                        return await self._accept(ctx, page, matches[0], target, 0.8, intent)
            return None
        finally:
            await self.monitor.stop(page)

    async def _accept(self, ctx: Any, page: Any, el: Any, target: TargetDescription, score: float, intent: str) -> ResolvedTarget | None:
        if not re.match(r"^tp-\d+$", el.element_id or ""):
            return None
        locator = page.locator(f'[data-tp-id="{el.element_id}"]')
        if await locator.count() != 1 or not await locator.is_visible() or not await locator.is_enabled():
            return None
        if intent == "type" and not await locator.is_editable():
            return None
        return ResolvedTarget(locator=locator, element=el, strategy="self-corrected", confidence=round(min(score, 0.9), 3), attempts=1)
