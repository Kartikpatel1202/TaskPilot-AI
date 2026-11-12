"""Sanitized failure evidence for recovery (and, optionally, an LLM suggestion).

Contains only: the failed action description, the expected target, a safe page summary (title + host
+ path, never query strings), candidate ACCESSIBLE NAMES of visible interactive controls (never input
values; sensitive fields omitted), recent relevant DOM change summaries and the permitted action types.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit

from app.core.logging import redact_text


@dataclass
class Candidate:
    role: str
    name: str


@dataclass
class FailureEvidence:
    failure_type: str
    action_description: str
    expected_target: str
    page_title: str | None
    page_location: str | None
    candidates: list[Candidate] = field(default_factory=list)
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    permitted_actions: list[str] = field(default_factory=lambda: ["click_existing_control", "none"])

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


def build_evidence(*, failure_type: str, description: str, expected: str, url: str | None, title: str | None,
                   elements: list[Any], events: list[dict[str, Any]], max_candidates: int = 25) -> FailureEvidence:
    loc = None
    if url:
        parts = urlsplit(url)
        loc = f"{parts.hostname or ''}{parts.path or ''}"[:200]
    candidates: list[Candidate] = []
    for el in elements:
        if getattr(el, "is_sensitive", False) or not getattr(el, "is_visible", True):
            continue
        name = (getattr(el, "accessible_name", None) or "").strip()
        if not name:
            continue
        candidates.append(Candidate(role=str(getattr(el, "role", "") or "")[:30], name=redact_text(name)[:80]))
        if len(candidates) >= max_candidates:
            break
    safe_events = [{"kind": str(e.get("kind", ""))[:20], "role": str(e.get("role", ""))[:20], "name": redact_text(str(e.get("name", "")))[:80]}
                   for e in events[-15:]]
    return FailureEvidence(failure_type=failure_type, action_description=redact_text(description)[:300], expected_target=redact_text(expected)[:200],
                           page_title=redact_text(title or "")[:120] or None, page_location=loc, candidates=candidates, recent_events=safe_events)
