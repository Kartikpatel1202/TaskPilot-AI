"""Structured (JSON-lines) logging with sensitive-data redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

SENSITIVE_KEY_PATTERN = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|authorization|cookie|session[_-]?token|"
    r"card|cvv|otp|credential)",
    re.IGNORECASE,
)
REDACTED = "[REDACTED]"

_STANDARD_RECORD_ATTRS = set(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()
) | {"message", "asctime", "taskName"}


def redact(value: Any, _depth: int = 0) -> Any:
    """Recursively redact values whose keys look sensitive. Bounded depth."""
    if _depth > 6:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {
            str(k): (REDACTED if SENSITIVE_KEY_PATTERN.search(str(k)) else redact(v, _depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v, _depth + 1) for v in value][:100]
    return value


# Free-text redaction for user content (memory, prompts, logs).
_TEXT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:\d[ -]?){12,18}\d\b"), "[REDACTED_CARD]"),
    (re.compile(r"\b(cvv|cvc)\s*(?:is|:|=)?\s*\d{3,4}\b", re.IGNORECASE), r"\1 [REDACTED]"),
    (
        re.compile(r"\b(otp|one[- ]time (?:password|code)|pin)\s*(?:is|hai|:|=)?\s*\d{4,8}\b", re.IGNORECASE),
        r"\1 [REDACTED]",
    ),
    (re.compile(r"\b(password|passwd|pwd|passcode)\s*(?:is|hai|:|=)\s*\S+", re.IGNORECASE), r"\1 [REDACTED]"),
    (re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE), "Bearer [REDACTED]"),
    (re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{12,}"), "[REDACTED_KEY]"),
    (re.compile(r"\b(api[_ -]?key|token|secret)\s*(?:is|:|=)\s*\S+", re.IGNORECASE), r"\1 [REDACTED]"),
)


def redact_text(text: str) -> str:
    """Mask card numbers, OTPs, passwords, CVVs and tokens in free text."""
    for pattern, replacement in _TEXT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extras = {k: v for k, v in record.__dict__.items() if k not in _STANDARD_RECORD_ATTRS}
        if extras:
            payload.update(redact(extras))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger("taskpilot")
    root.setLevel(level)
    if not any(getattr(h, "_taskpilot", False) for h in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        handler._taskpilot = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"taskpilot.{name}")
