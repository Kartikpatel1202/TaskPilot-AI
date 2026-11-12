"""Bounded execution queue: fixed worker pool, one active task per session.

* `submit` never blocks and never exceeds `maxsize` (full → ExecutionQueueFullError).
* A task id or a session id can only be queued/in flight once at a time.
* Running jobs can be cancelled individually; shutdown cancels everything and
  reports every unfinished job through `on_abandoned`.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from app.core.logging import get_logger

logger = get_logger("execution.queue")


@dataclass(frozen=True)
class ExecutionJob:
    task_id: UUID
    session_id: UUID


class ExecutionQueueFullError(RuntimeError):
    pass


class ExecutionAlreadyActiveError(RuntimeError):
    pass


class ExecutionQueueClosedError(RuntimeError):
    pass


class ExecutionQueue:
    def __init__(
        self,
        handler: Callable[[ExecutionJob], Awaitable[None]],
        *,
        concurrency: int,
        maxsize: int,
        on_abandoned: Callable[[ExecutionJob, str], Awaitable[None]],
    ) -> None:
        self._handler = handler
        self._concurrency = concurrency
        self._queue: asyncio.Queue[ExecutionJob] = asyncio.Queue(maxsize=maxsize)
        self._on_abandoned = on_abandoned
        self._workers: list[asyncio.Task[None]] = []
        self._tasks: set[UUID] = set()
        self._sessions: set[UUID] = set()
        self._running: dict[UUID, asyncio.Task[None]] = {}
        self._dequeued: set[UUID] = set()
        self._closed = True

    async def start(self) -> None:
        if self._workers:
            return
        self._closed = False
        self._workers = [asyncio.create_task(self._worker(), name=f"execution-worker-{i}") for i in range(self._concurrency)]

    async def stop(self) -> None:
        self._closed = True
        for task in list(self._running.values()):
            task.cancel()
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []
        while not self._queue.empty():
            job = self._queue.get_nowait()
            self._queue.task_done()
            self._release(job)
            with contextlib.suppress(Exception):
                await self._on_abandoned(job, "SERVER_SHUTDOWN")

    @property
    def is_full(self) -> bool:
        return self._queue.full()

    def is_active(self, task_id: UUID) -> bool:
        return task_id in self._tasks

    def session_busy(self, session_id: UUID) -> bool:
        return session_id in self._sessions

    def is_running(self, task_id: UUID) -> bool:
        return task_id in self._running

    def submit(self, job: ExecutionJob) -> None:
        if self._closed:
            raise ExecutionQueueClosedError("Execution is shutting down.")
        if job.task_id in self._tasks or job.session_id in self._sessions:
            raise ExecutionAlreadyActiveError("An execution is already queued or running for this task/session.")
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull as exc:
            raise ExecutionQueueFullError("The execution queue is full.") from exc
        self._tasks.add(job.task_id)
        self._sessions.add(job.session_id)

    def withdraw_queued(self, task_id: UUID) -> bool:
        """Mark a queued (not yet running) job so the worker drops it."""
        if task_id in self._tasks and task_id not in self._running:
            self._dequeued.add(task_id)
            return True
        return False

    def cancel_running(self, task_id: UUID) -> bool:
        task = self._running.get(task_id)
        if task is None:
            return False
        task.cancel()
        return True

    async def join(self) -> None:
        await self._queue.join()

    def _release(self, job: ExecutionJob) -> None:
        self._tasks.discard(job.task_id)
        self._sessions.discard(job.session_id)
        self._running.pop(job.task_id, None)
        self._dequeued.discard(job.task_id)

    async def _worker(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                if job.task_id in self._dequeued:
                    await self._on_abandoned(job, "USER_CANCELLED")
                    continue
                run = asyncio.create_task(self._handler(job), name=f"execution-{job.task_id}")
                self._running[job.task_id] = run
                try:
                    # The handler finalises its own task state when cancelled (shielded).
                    await run
                except asyncio.CancelledError:
                    if self._closed:
                        raise
                except Exception:
                    logger.exception("execution.job_crashed", extra={"task_id": str(job.task_id)})
                    with contextlib.suppress(Exception):
                        await self._on_abandoned(job, "EXECUTION_WORKER_ERROR")
            finally:
                self._release(job)
                self._queue.task_done()
