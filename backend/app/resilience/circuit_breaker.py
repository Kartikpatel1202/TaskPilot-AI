"""Circuit breaker (CLOSED -> OPEN -> HALF_OPEN) with a single half-open probe.

Only transient failures count: callers pass `is_failure` so permanent errors (bad credentials,
invalid configuration, validation) never open the circuit and are never retried as transient.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import TypeVar

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(RuntimeError):
    def __init__(self, name: str, retry_after: float) -> None:
        self.name = name
        self.retry_after = retry_after
        super().__init__(f"{name} is temporarily unavailable (circuit open).")


class CircuitBreaker:
    def __init__(self, name: str, *, failure_threshold: int = 5, recovery_seconds: float = 30, clock: Callable[[], float] = time.monotonic) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._clock = clock
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.opened_at = 0.0
        self.total_opens = 0
        self._probe = asyncio.Lock()

    def _maybe_half_open(self) -> None:
        if self.state == CircuitState.OPEN and self._clock() - self.opened_at >= self.recovery_seconds:
            self.state = CircuitState.HALF_OPEN

    async def call(self, work: Callable[[], Awaitable[T]], *, is_failure: Callable[[BaseException], bool] = lambda e: True) -> T:
        self._maybe_half_open()
        if self.state == CircuitState.OPEN:
            raise CircuitOpenError(self.name, self.recovery_seconds - (self._clock() - self.opened_at))
        if self.state == CircuitState.HALF_OPEN:
            if self._probe.locked():  # only one probe at a time; others fail fast
                raise CircuitOpenError(self.name, 1.0)
            async with self._probe:
                return await self._attempt(work, is_failure)
        return await self._attempt(work, is_failure)

    async def _attempt(self, work: Callable[[], Awaitable[T]], is_failure: Callable[[BaseException], bool]) -> T:
        try:
            result = await work()
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError) or not is_failure(exc):
                if self.state == CircuitState.HALF_OPEN:
                    self.state = CircuitState.CLOSED  # a permanent error still proves the dependency answers
                raise
            self.record_failure()
            raise
        self.record_success()
        return result

    def record_failure(self) -> None:
        self.failures += 1
        if self.state == CircuitState.HALF_OPEN or self.failures >= self.failure_threshold:
            if self.state != CircuitState.OPEN:
                self.total_opens += 1
            self.state = CircuitState.OPEN
            self.opened_at = self._clock()

    def record_success(self) -> None:
        self.failures = 0
        self.state = CircuitState.CLOSED

    def snapshot(self) -> dict[str, object]:
        self._maybe_half_open()
        return {"name": self.name, "state": self.state.value, "failures": self.failures, "opens": self.total_opens}
