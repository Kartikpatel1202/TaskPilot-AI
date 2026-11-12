"""Distributed locks with ownership tokens: SET NX PX, atomic check-and-release / check-and-renew.
Locks always expire (no permanent locks); a holder renews while it works."""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

_RELEASE = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end"
_RENEW = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('PEXPIRE', KEYS[1], ARGV[2]) else return 0 end"


class LockNotAcquiredError(RuntimeError):
    pass


class RedisLock:
    def __init__(self, redis: Any, key: str, *, ttl_ms: int = 30_000) -> None:
        self.r = redis
        self.key = key
        self.ttl_ms = ttl_ms
        self.token = secrets.token_hex(16)
        self._release = redis.register_script(_RELEASE)
        self._renew = redis.register_script(_RENEW)

    async def acquire(self, wait_seconds: float = 0) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_seconds
        while True:
            if await self.r.set(self.key, self.token, nx=True, px=self.ttl_ms):
                return True
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(0.1)

    async def renew(self) -> bool:
        return bool(await self._renew(keys=[self.key], args=[self.token, self.ttl_ms]))

    async def release(self) -> bool:
        return bool(await self._release(keys=[self.key], args=[self.token]))


class SessionLocks:
    """One active mutation per browser session across processes (Redis) — or in-process otherwise."""

    def __init__(self, redis: Any | None, *, ttl_ms: int = 30_000, prefix: str = "tp:lock:session:") -> None:
        self.r = redis
        self.ttl_ms = ttl_ms
        self.prefix = prefix

    @asynccontextmanager
    async def hold(self, session_id: object, wait_seconds: float = 5) -> AsyncIterator[None]:
        if self.r is None:
            yield
            return
        lock = RedisLock(self.r, f"{self.prefix}{session_id}", ttl_ms=self.ttl_ms)
        if not await lock.acquire(wait_seconds):
            raise LockNotAcquiredError("Another worker is already running a task in this browser session.")

        async def keep_alive() -> None:
            while True:
                await asyncio.sleep(self.ttl_ms / 3000)
                if not await lock.renew():
                    return

        renewer = asyncio.create_task(keep_alive())
        try:
            yield
        finally:
            renewer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await renewer
            with contextlib.suppress(Exception):
                await lock.release()
