"""Dead-letter inspection (operators): list failed jobs with their last error, requeue one explicitly."""

from __future__ import annotations

from typing import Any

from app.queue.redis_queue import RedisJobQueue


async def dead_letter_report(queue: RedisJobQueue, limit: int = 50) -> list[dict[str, Any]]:
    return [{"job_id": j.job_id, "kind": j.kind, "attempts": j.attempts, "last_error": j.last_error,
             "dedupe_key": j.dedupe_key} for j in await queue.dead_letters(limit)]


async def requeue(queue: RedisJobQueue, job_id: str) -> bool:
    """Explicit operator action only — dead letters are never retried automatically."""
    return await queue.requeue_dead(job_id)
