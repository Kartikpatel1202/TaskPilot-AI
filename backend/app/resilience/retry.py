"""Bounded exponential backoff with full jitter — ONLY for operations proven idempotent/transient.

Never use this for order submission, calendar creation, draft saves, cart mutations or deletions:
those go through the execution journal and reconciliation instead.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


def backoff_delay(attempt: int, *, base: float = 0.5, cap: float = 10.0, rng: random.Random | None = None) -> float:
    """Full jitter: uniform(0, min(cap, base * 2**attempt))."""
    r = rng or random
    return r.uniform(0, min(cap, base * (2 ** max(0, attempt))))


async def retry_async(work: Callable[[], Awaitable[T]], *, attempts: int, is_transient: Callable[[BaseException], bool],
                      base: float = 0.5, cap: float = 10.0, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> T:
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    for attempt in range(attempts):
        try:
            return await work()
        except Exception as exc:
            if attempt == attempts - 1 or not is_transient(exc):
                raise
            await sleep(backoff_delay(attempt, base=base, cap=cap))
    raise AssertionError("unreachable")
