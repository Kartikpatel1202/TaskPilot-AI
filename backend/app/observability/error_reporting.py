"""Error reporting hook: structured, redacted log + counter. A deployment can plug in an external
reporter (e.g. Sentry) by replacing `reporter`; nothing here sends data anywhere by default."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.logging import get_logger

logger = get_logger("errors")
reporter: Callable[[BaseException, dict[str, Any]], None] | None = None


def report(exc: BaseException, *, component: str, metrics: Any | None = None, **context: Any) -> None:
    logger.error("error.reported", exc_info=exc, extra={"component": component, **{k: v for k, v in context.items() if k != "exc"}})
    if metrics is not None:
        metrics.errors.labels(component=component[:30]).inc()
    if reporter is not None:
        try:
            reporter(exc, {"component": component, **context})
        except Exception:  # noqa: BLE001
            logger.warning("error.reporter_failed")
