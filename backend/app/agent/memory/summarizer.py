"""Deterministic summariser used when a session exceeds its character budget.

No LLM call: older turns are compressed into short, redacted one-liners so the
most important facts (what was asked, which intent) survive truncation.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.schemas.memory import ConversationRole, ConversationTurn

MAX_SUMMARY_CHARS = 1500
_PER_TURN = 140


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def summarize_turns(turns: Iterable[ConversationTurn], previous: str | None = None) -> str:
    lines = [previous] if previous else []
    for turn in turns:
        who = "User" if turn.role == ConversationRole.USER else "Kamlesh Bhai"
        intent = f" [{turn.intent.value}]" if turn.intent else ""
        lines.append(f"{who}{intent}: {_clip(turn.content, _PER_TURN)}")
    summary = "\n".join(lines)
    # Keep the most recent part when the summary itself overflows.
    return summary if len(summary) <= MAX_SUMMARY_CHARS else "…" + summary[-(MAX_SUMMARY_CHARS - 1) :]
