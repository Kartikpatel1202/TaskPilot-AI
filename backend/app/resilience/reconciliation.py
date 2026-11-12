"""Turn an execution journal into an honest reconciliation note (what certainly happened, what is unknown)."""

from __future__ import annotations

from typing import Any

from app.database.models import ActionLifecycle


def journal_summary(rows: list[Any]) -> tuple[list[int], list[int], str]:
    """(succeeded step orders, unknown step orders, human note)."""
    done = [r.step_order for r in rows if r.lifecycle == ActionLifecycle.SUCCEEDED.value]
    unknown = [r.step_order for r in rows if r.lifecycle == ActionLifecycle.UNKNOWN.value]
    parts = ["The server restarted while this task was running; it was not resumed automatically."]
    if done:
        parts.append(f"Verified before the restart: step(s) {', '.join(map(str, done))}.")
    if unknown:
        parts.append(f"Step(s) {', '.join(map(str, unknown))} may or may not have changed the website — "
                     "check the site (cart, drafts, calendar, order) before running the task again.")
    elif not done:
        parts.append("No step had completed.")
    return done, unknown, " ".join(parts)
