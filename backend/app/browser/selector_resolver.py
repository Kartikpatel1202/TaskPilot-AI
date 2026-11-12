"""Semantic selector resolution.

The planner describes targets in words ("Product search box", role hint
"textbox"); it never supplies CSS or XPath. Resolution order:

  1. verified cache metadata (role + name), always revalidated
  2. accessible role + exact name        (Playwright get_by_role)
  3. associated label / aria-label       (get_by_label)
  4. placeholder                         (get_by_placeholder)
  5. exact visible text                  (get_by_text)
  6. semantic scoring over fresh DOM inspector candidates

A target is accepted only if it is unique (or clearly the best by a margin),
visible, enabled, attached, role-compatible and scores at least
BROWSER_SELECTOR_MIN_CONFIDENCE. Ties are refused — nothing is clicked at random.
The only CSS ever built is `[data-tp-id="tp-N"]`, an id assigned by the trusted
DOM inspector and validated by regex.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

from app.browser.dom_inspector import TP_ID, DOMInspector
from app.browser.errors import SelectorAmbiguousError, SelectorResolutionError
from app.core.logging import get_logger
from app.schemas.browser import DOMElementInfo, TargetDescription

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page

logger = get_logger("browser.resolver")

Intent = Literal["click", "type"]
AMBIGUITY_MARGIN = 0.05
STRATEGY_CONFIDENCE = {"cache": 0.98, "role+name": 0.99, "label": 0.97, "placeholder": 0.95, "text": 0.93}

GENERIC = frozenset(
    "the a an for to of on in at with and or this that it its your my user please "
    "matching matched relevant selected correct requested desired specific first best "
    "button btn field input box link icon element control area section product products item items "
    "result results page website site option options tab".split()
)
SYNONYMS = {
    "l": "litre", "ltr": "litre", "liter": "litre", "litres": "litre", "liters": "litre",
    "gm": "g", "gram": "g", "grams": "g", "kgs": "kg", "kilo": "kg", "pcs": "piece", "pieces": "piece",
    "qty": "quantity", "doodh": "milk", "basket": "cart", "bag": "cart",
}
ROLE_GROUPS = [
    {"textbox", "searchbox", "combobox"},
    {"button"},
    {"link"},
    {"checkbox", "switch"},
    {"radio"},
    {"tab"},
    {"menuitem", "option"},
]


def tokens(*texts: str | None) -> set[str]:
    out: set[str] = set()
    for text in texts:
        if not text:
            continue
        norm = unicodedata.normalize("NFKD", text.lower())
        for raw in re.findall(r"[a-z0-9ऀ-ॿ]+", norm):
            word = SYNONYMS.get(raw, raw)
            if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
                word = word[:-1]
            word = SYNONYMS.get(word, word)
            out.add(word)
    return out


def significant(*texts: str | None) -> set[str]:
    return {t for t in tokens(*texts) if t not in GENERIC}


def _norm(text: str | None) -> str:
    return " ".join(sorted(tokens(text))) if text else ""


def role_score(hint: str | None, role: str | None) -> float:
    if not hint:
        return 0.7
    hint, role = hint.lower(), (role or "").lower()
    if hint == role or any(hint in g and role in g for g in ROLE_GROUPS):
        return 1.0
    if {hint, role} == {"button", "link"}:
        return 0.6  # models often call a link-styled control a button
    return 0.0


def coverage(wanted: set[str], have: set[str]) -> float:
    return len(wanted & have) / len(wanted) if wanted else 0.0


def score_candidate(target: TargetDescription, el: DOMElementInfo) -> float:
    r = role_score(target.role_hint, el.role)
    if r == 0.0:
        return 0.0
    hints = [h for h in (target.accessible_name, target.text_hint) if h]
    t_tokens = significant(target.description, *hints) or tokens(target.description)
    h_tokens = significant(*hints) or t_tokens
    name_tokens = tokens(el.accessible_name, el.placeholder, el.aria_label, el.label, el.text_content)
    exact = any(_norm(h) and _norm(h) in {_norm(el.accessible_name), _norm(el.placeholder), _norm(el.label)} for h in hints)
    name_match = 1.0 if exact else coverage(h_tokens, name_tokens)
    context_match = coverage(t_tokens, name_tokens | tokens(el.context_text))
    return round(0.5 * name_match + 0.2 * r + 0.3 * context_match, 4)


@dataclass
class ResolvedTarget:
    locator: Locator
    element: DOMElementInfo
    strategy: str
    confidence: float
    attempts: int


class SelectorResolver:
    def __init__(
        self, inspector: DOMInspector, *, min_confidence: float, max_attempts: int, cache_size: int = 256,
        memory_ttl_seconds: float = 1800,
    ) -> None:
        self._inspector = inspector
        self.min_confidence = min_confidence
        self.max_attempts = max_attempts
        from app.browser.selector_memory import SelectorMemory

        # Phase 6: verified metadata with expiry (never live locators); revalidated on every reuse.
        self.memory = SelectorMemory(ttl_seconds=memory_ttl_seconds, max_entries=cache_size)

    # ---------------------------------------------------------------- public

    async def resolve(self, page: Page, target: TargetDescription, intent: Intent = "click") -> ResolvedTarget:
        last: SelectorResolutionError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                resolved = await self._resolve_once(page, target, intent)
                resolved.attempts = attempt
                return resolved
            except SelectorAmbiguousError:
                raise  # never "heal" ambiguity by guessing
            except SelectorResolutionError as exc:
                last = exc
                if attempt < self.max_attempts:
                    # Self-healing: let the DOM settle, then re-inspect from scratch.
                    await page.wait_for_timeout(400 * attempt)
        assert last is not None
        raise last

    # ---------------------------------------------------------------- internals

    def _cache_key(self, page: Page, target: TargetDescription) -> tuple[str, ...]:
        parts = urlsplit(page.url)
        section = parts.path.strip("/").split("/")[0] if parts.path else ""
        return (parts.netloc.lower(), section, _norm(target.description), (target.role_hint or "").lower())

    async def _resolve_once(self, page: Page, target: TargetDescription, intent: Intent) -> ResolvedTarget:
        candidates = await self._inspector.inspect_interactables(page)
        usable = [c for c in candidates if c.element_id and (intent != "type" or c.is_editable or c.is_sensitive)]
        by_id = {c.element_id: c for c in usable}

        # 1. cached metadata — revalidated against the fresh DOM, never trusted blindly
        cached = self.memory.get(self._cache_key(page, target))
        if cached:
            role, name = cached.role, cached.accessible_name
            hits = [c for c in usable if c.role == role and _norm(c.accessible_name) == _norm(name)]
            if len(hits) == 1:
                return await self._accept(page, hits[0], "cache", STRATEGY_CONFIDENCE["cache"], target, intent)

        # 2-5. Playwright accessible locators with exact matching
        for strategy, locator in self._exact_locators(page, target):
            ids = await self._ids_for(locator)
            matches = [by_id[i] for i in ids if i in by_id and role_score(target.role_hint, by_id[i].role) > 0]
            if len(matches) == 1:
                # A unique name match must still fit the described context (e.g. the only
                # "Add" button on the page may belong to a different product).
                if score_candidate(target, matches[0]) >= self.min_confidence:
                    return await self._accept(page, matches[0], strategy, STRATEGY_CONFIDENCE[strategy], target, intent)
                continue
            if len(matches) > 1:
                return await self._disambiguate(page, matches, target, intent, strategy)

        # 6. semantic scoring over every usable candidate
        return await self._disambiguate(page, usable, target, intent, "semantic")

    def _exact_locators(self, page: Page, target: TargetDescription) -> list[tuple[str, Locator]]:
        out: list[tuple[str, Locator]] = []
        role = (target.role_hint or "").lower()
        name = target.accessible_name or target.text_hint
        if role and name:
            roles = next((sorted(g) for g in ROLE_GROUPS if role in g), [role])
            for r in roles:
                out.append(("role+name", page.get_by_role(r, name=name, exact=True)))  # type: ignore[arg-type]
        if target.accessible_name:
            out.append(("label", page.get_by_label(target.accessible_name, exact=True)))
            out.append(("placeholder", page.get_by_placeholder(target.accessible_name, exact=True)))
        if target.text_hint:
            out.append(("placeholder", page.get_by_placeholder(target.text_hint, exact=True)))
            out.append(("text", page.get_by_text(target.text_hint, exact=True)))
        return out

    async def _ids_for(self, locator: Locator) -> list[str]:
        try:
            ids = await locator.evaluate_all(
                "els => els.map(e => (e.closest('[data-tp-id]') || {dataset: {}}).dataset.tpId || null)"
            )
        except Exception:  # detached / navigation in progress
            return []
        return list(dict.fromkeys(i for i in ids if isinstance(i, str) and TP_ID.match(i)))

    async def _disambiguate(
        self, page: Page, pool: list[DOMElementInfo], target: TargetDescription, intent: Intent, strategy: str
    ) -> ResolvedTarget:
        scored = sorted(((score_candidate(target, c), c) for c in pool), key=lambda x: x[0], reverse=True)
        scored = [(s, c) for s, c in scored if s > 0]
        if not scored or scored[0][0] < self.min_confidence:
            best = scored[0][0] if scored else 0.0
            raise SelectorResolutionError(
                f"No element confidently matches “{target.description}” (best score {best:.2f})."
            )
        best_score, best = scored[0]
        rivals = [c for s, c in scored[1:] if s >= self.min_confidence and best_score - s < AMBIGUITY_MARGIN]
        if rivals:
            raise SelectorAmbiguousError(
                f"{len(rivals) + 1} elements match “{target.description}” equally well; refusing to choose one."
            )
        label = strategy if strategy == "semantic" else f"{strategy}+context"
        return await self._accept(page, best, label, best_score, target, intent)

    async def _accept(
        self, page: Page, el: DOMElementInfo, strategy: str, confidence: float, target: TargetDescription, intent: Intent
    ) -> ResolvedTarget:
        assert el.element_id and TP_ID.match(el.element_id)
        locator = page.locator(f'[data-tp-id="{el.element_id}"]')
        if await locator.count() != 1:
            raise SelectorResolutionError("The matched element detached from the page.")
        if not await locator.is_visible():
            raise SelectorResolutionError("The matched element is not visible.")
        if not el.is_enabled or not await locator.is_enabled():
            raise SelectorResolutionError(f"“{target.description}” is disabled.", code="ELEMENT_DISABLED")
        if intent == "type" and not el.is_sensitive and not await locator.is_editable():
            raise SelectorResolutionError(f"“{target.description}” is not an editable field.")
        if confidence < self.min_confidence:
            raise SelectorResolutionError(f"Match confidence {confidence:.2f} is below the threshold.")
        stable = {k: v for k, v in (("aria-label", el.aria_label), ("placeholder", el.placeholder)) if v}
        self.memory.remember(self._cache_key(page, target), el.role, el.accessible_name, stable)
        logger.info("selector.resolved", extra={"strategy": strategy, "confidence": round(confidence, 3), "role": el.role})
        return ResolvedTarget(locator=locator, element=el, strategy=strategy, confidence=confidence, attempts=1)
