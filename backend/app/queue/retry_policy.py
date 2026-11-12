"""Retry policy for queue jobs: bounded attempts, backoff with jitter, permanent errors never retried."""

from __future__ import annotations

from dataclasses import dataclass

from app.resilience.retry import backoff_delay

PERMANENT_CODES = frozenset({"VALIDATION_ERROR", "PLAN_NOT_FOUND", "TASK_NOT_FOUND", "ACTION_STATE_UNKNOWN", "UNAUTHORIZED",
                             "CONFIGURATION_ERROR"})


class PermanentJobError(Exception):
    """A job that must not be retried (bad input, missing records, uncertain mutation)."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_seconds: float = 1.0
    cap_seconds: float = 30.0

    def should_retry(self, attempts: int, exc: BaseException) -> bool:
        if isinstance(exc, PermanentJobError) or getattr(exc, "code", None) in PERMANENT_CODES:
            return False
        return attempts < self.max_attempts

    def delay(self, attempts: int) -> float:
        return backoff_delay(attempts, base=self.base_seconds, cap=self.cap_seconds)
