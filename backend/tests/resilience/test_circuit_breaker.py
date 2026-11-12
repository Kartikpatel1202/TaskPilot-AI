"""Circuit breaker states, permanent-error handling, single half-open probe, and bounded jittered retries."""

from __future__ import annotations

import asyncio
import random

import pytest

from app.resilience.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState
from app.resilience.retry import backoff_delay, retry_async


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


async def _fail() -> None:
    raise TimeoutError("slow")


async def _ok() -> str:
    return "ok"


async def test_opens_after_threshold_then_half_opens_and_closes() -> None:
    clock = Clock()
    cb = CircuitBreaker("llm", failure_threshold=2, recovery_seconds=10, clock=clock)
    for _ in range(2):
        with pytest.raises(TimeoutError):
            await cb.call(_fail)
    assert cb.state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        await cb.call(_ok)  # fails fast, the provider is not called
    clock.t = 11
    assert await cb.call(_ok) == "ok" and cb.state == CircuitState.CLOSED


async def test_permanent_errors_never_open_the_circuit() -> None:
    cb = CircuitBreaker("llm", failure_threshold=1)

    async def auth_error() -> None:
        raise PermissionError("bad key")

    for _ in range(3):
        with pytest.raises(PermissionError):
            await cb.call(auth_error, is_failure=lambda e: not isinstance(e, PermissionError))
    assert cb.state == CircuitState.CLOSED


async def test_half_open_allows_a_single_probe() -> None:
    clock = Clock()
    cb = CircuitBreaker("redis", failure_threshold=1, recovery_seconds=1, clock=clock)
    with pytest.raises(TimeoutError):
        await cb.call(_fail)
    clock.t = 2
    gate = asyncio.Event()

    async def slow_ok() -> str:
        await gate.wait()
        return "ok"

    probe = asyncio.create_task(cb.call(slow_ok))
    await asyncio.sleep(0)
    with pytest.raises(CircuitOpenError):
        await cb.call(_ok)
    gate.set()
    assert await probe == "ok"


async def test_retry_is_bounded_and_skips_permanent_errors() -> None:
    sleeps: list[float] = []

    async def sleep(s: float) -> None:
        sleeps.append(s)

    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        raise ConnectionError("x")

    with pytest.raises(ConnectionError):
        await retry_async(flaky, attempts=3, is_transient=lambda e: isinstance(e, ConnectionError), sleep=sleep)
    assert calls["n"] == 3 and len(sleeps) == 2
    calls["n"] = 0
    with pytest.raises(ConnectionError):
        await retry_async(flaky, attempts=3, is_transient=lambda e: False, sleep=sleep)
    assert calls["n"] == 1
    rng = random.Random(1)
    assert all(0 <= backoff_delay(a, base=0.5, cap=4, rng=rng) <= min(4, 0.5 * 2**a) for a in range(8))
