"""Redis-backed execution dispatch with the ExecutionQueue interface used by ExecutionManager.

Run Plan enqueues a durable job (bounded, one live job per task). A QueueWorker in this process
consumes it and calls the same `run` coroutine the in-process queue uses. Jobs that were queued
when the process died survive in Redis and run after restart — but only if the task is still
PLANNED; anything already started is reconciled by recovery + the execution journal, never re-run.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.execution.execution_queue import ExecutionJob, ExecutionQueueFullError
from app.queue.base import Job, QueueFullError
from app.queue.job_registry import JobRegistry
from app.queue.redis_queue import RedisJobQueue
from app.queue.worker import QueueWorker

logger = get_logger("queue.execution")


class RedisExecutionQueue:
    def __init__(self, redis: Any, run: Callable[[ExecutionJob], Awaitable[None]], *, concurrency: int, max_depth: int,
                 max_attempts: int, heartbeat_seconds: int, metrics: Any | None = None,
                 should_run: Callable[[ExecutionJob], Awaitable[bool]] | None = None,
                 on_abandoned: Callable[[ExecutionJob, str], Awaitable[None]] | None = None) -> None:
        self.queue = RedisJobQueue(redis, "execution", max_depth=max_depth, max_attempts=max_attempts)
        self._run = run
        self._should_run = should_run
        self._on_abandoned = on_abandoned
        registry = JobRegistry()
        registry.register("execution", self._handle)
        self.worker = QueueWorker(self.queue, registry, heartbeat_seconds=heartbeat_seconds, concurrency=concurrency, metrics=metrics)
        self.max_depth = max_depth
        self._active: dict[UUID, UUID] = {}     # task -> session (queued or running in this process)
        self._running: set[UUID] = set()
        self._withdrawn: set[UUID] = set()

    async def start(self) -> None:
        await self.worker.start()

    async def stop(self) -> None:
        await self.worker.stop()

    async def enqueue(self, job: ExecutionJob) -> None:
        try:
            await self.queue.enqueue(Job(kind="execution", payload={"task_id": str(job.task_id), "session_id": str(job.session_id)},
                                         dedupe_key=f"task:{job.task_id}"))
        except QueueFullError as exc:
            raise ExecutionQueueFullError(str(exc)) from exc
        self._active[job.task_id] = job.session_id

    async def _handle(self, payload: dict[str, Any]) -> None:
        job = ExecutionJob(UUID(payload["task_id"]), UUID(payload["session_id"]))
        if job.task_id in self._withdrawn:
            self._withdrawn.discard(job.task_id)
            self._active.pop(job.task_id, None)
            if self._on_abandoned is not None:
                await self._on_abandoned(job, "USER_CANCELLED")
            return
        if self._should_run is not None and not await self._should_run(job):
            logger.info("execution.job_skipped_not_runnable", extra={"task_id": str(job.task_id)})
            self._active.pop(job.task_id, None)
            return
        self._active[job.task_id] = job.session_id
        self._running.add(job.task_id)
        try:
            await self._run(job)
        finally:
            self._running.discard(job.task_id)
            self._active.pop(job.task_id, None)

    # ---------------------------------------------------------------- ExecutionQueue-compatible view

    def is_active(self, task_id: UUID) -> bool:
        return task_id in self._active

    def is_running(self, task_id: UUID) -> bool:
        return task_id in self._running

    def session_busy(self, session_id: UUID) -> bool:
        return session_id in self._active.values()

    @property
    def is_full(self) -> bool:
        return len(self._active) >= self.max_depth

    def withdraw_queued(self, task_id: UUID) -> bool:
        if task_id in self._active and task_id not in self._running:
            self._withdrawn.add(task_id)
            return True
        return False
