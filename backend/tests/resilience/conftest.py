"""Resilience tests. Redis-backed tests use the LOCAL Redis (db 15, unique key prefixes) and are skipped
when no Redis server is reachable — they never touch a shared or remote Redis."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

REDIS_URL = os.environ.get("TASKPILOT_TEST_REDIS_URL", "redis://localhost:6379/15")


def redis_available() -> bool:
    try:
        import redis

        return bool(redis.Redis.from_url(REDIS_URL, socket_connect_timeout=0.5).ping())
    except Exception:  # noqa: BLE001
        return False


needs_redis = pytest.mark.skipif(not redis_available(), reason="local Redis (localhost:6379) not running")


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[object]:
    from redis.asyncio import from_url

    client = from_url(REDIS_URL, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def prefix() -> str:
    return f"tp:test:{uuid.uuid4().hex[:8]}:"
