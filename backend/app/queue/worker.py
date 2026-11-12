"""Queue worker: heartbeat, reserve -> handle -> ack/nack, periodic reaping of dead workers, graceful stop.

In this release the worker runs INSIDE the API process (QUEUE_BACKEND=redis, one API replica that
also owns the browser). A separate browser-worker process would additionally need cross-process
bridging of telemetry, approvals and the binary screenshot stream — not implemented yet
(see docs/PRODUCTION_ARCHITECTURE.md).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import time
from typing import Any
from uuid import uuid4

from app.core.logging import get_logger
from app.queue.job_registry import JobRegistry
from app.queue.redis_queue import RedisJobQueue
from app.queue.retry_policy import RetryPolicy

logger = get_logger("queue.worker")


def new_worker_id() -> str:
    return f"{socket.gethostname()[:30]}-{os.getpid()}-{uuid4().hex[:6]}"


class QueueWorker:
    def __init__(self, queue: RedisJobQueue, registry: JobRegistry, *, worker_id: str | None = None, heartbeat_seconds: int = 10,
                 concurrency: int = 1, policy: RetryPolicy | None = None, metrics: Any | None = None) -> None:
        self.queue = queue
        self.registry = registry
        self.worker_id = worker_id or new_worker_id()
        self.heartbeat_seconds = heartbeat_seconds
        self.concurrency = concurrency
        self.policy = policy or RetryPolicy(max_attempts=queue.max_attempts)
        self.metrics = metrics
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        self.processed = 0
        self.failed = 0

    async def start(self) -> None:
        await self.queue.heartbeat(self.worker_id, self.heartbeat_seconds * 3)
        await self.queue.reap()  # jobs of workers that died while this one was down
        self._tasks = [asyncio.create_task(self._heartbeat(), name="queue-heartbeat")]
        self._tasks += [asyncio.create_task(self._loop(), name=f"queue-worker-{i}") for i in range(self.concurrency)]

    async def stop(self, grace_seconds: float = 10) -> None:
        """Stop reserving new jobs; let running jobs finish within the grace period."""
        self._stop.set()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.gather(*self._tasks[1:], return_exceptions=True), timeout=grace_seconds)
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        with contextlib.suppress(Exception):
            await self.queue.r.delete(self.queue.heartbeat_prefix + self.worker_id)

    async def _heartbeat(self) -> None:
        while not self._stop.is_set():
            try:
                await self.queue.heartbeat(self.worker_id, self.heartbeat_seconds * 3)
                await self.queue.reap()
                if self.metrics is not None:
                    self.metrics.queue_depth.labels(queue=self.queue.name).set(await self.queue.depth())
            except Exception:  # noqa: BLE001
                logger.warning("queue.heartbeat_failed")
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self.heartbeat_seconds)

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                reserved = await self.queue.reserve(self.worker_id, timeout=1)
            except Exception:  # noqa: BLE001 - Redis hiccup: back off and try again
                logger.warning("queue.reserve_failed")
                await asyncio.sleep(1)
                continue
            if reserved is None:
                continue
            job, raw = reserved
            await self.run_one(job, raw)

    async def run_one(self, job: Any, raw: str) -> None:
        if self.metrics is not None:
            self.metrics.queue_wait.labels(queue=self.queue.name).observe(max(0.0, time.time() - job.enqueued_at))
        handler = self.registry.get(job.kind)
        if handler is None:
            job.attempts = self.queue.max_attempts  # unknown kinds go straight to the dead-letter list
            await self.queue.nack(self.worker_id, raw, job, f"unknown job kind {job.kind!r}")
            return
        try:
            await handler(job.payload)
        except Exception as exc:  # noqa: BLE001
            self.failed += 1
            retry = self.policy.should_retry(job.attempts + 1, exc)
            if not retry:
                job.attempts = self.queue.max_attempts - 1
            outcome = await self.queue.nack(self.worker_id, raw, job, f"{type(exc).__name__}: {str(exc)[:200]}")
            logger.warning("queue.job_failed", extra={"kind": job.kind, "outcome": outcome})
            if outcome == "retried":
                await asyncio.sleep(self.policy.delay(job.attempts))
            return
        await self.queue.ack(self.worker_id, raw, job)
        self.processed += 1
