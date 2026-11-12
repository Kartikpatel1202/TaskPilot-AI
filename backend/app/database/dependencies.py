"""Persistence facade used by the services (write-through: the database is authoritative,
in-memory structures are caches). Best-effort writes log and count failures instead of crashing
an execution; critical writes (task creation, approval consumption) propagate errors."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any, TypeVar

from app.core.logging import get_logger
from app.database.repositories import (
    ApprovalRepository,
    AuditRepository,
    ConversationRepository,
    ExecutionRepository,
    FileRepository,
    PlanRepository,
    SessionRepository,
    TaskRepository,
    UserRepository,
    WorkflowRepository,
)
from app.database.session import Database

logger = get_logger("persistence")
T = TypeVar("T")


class Persistence:
    def __init__(self, db: Database, *, memory_max_turns: int = 20, memory_ttl_minutes: int = 60) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.sessions = SessionRepository(db)
        self.tasks = TaskRepository(db)
        self.plans = PlanRepository(db)
        self.journal = ExecutionRepository(db)
        self.approvals = ApprovalRepository(db)
        self.workflows = WorkflowRepository(db)
        self.conversations = ConversationRepository(db, max_turns=memory_max_turns, ttl_minutes=memory_ttl_minutes)
        self.files = FileRepository(db)
        self.audit = AuditRepository(db)
        self.write_failures = 0
        self._inflight: set[asyncio.Task[Any]] = set()

    async def best_effort(self, work: Awaitable[T], what: str) -> T | None:
        """Run a write that must not be lost if the CALLER is cancelled (e.g. a worker stopping at shutdown):
        the write continues in its own task and `drain()` waits for it before the database closes."""

        async def _run() -> T | None:
            try:
                return await work
            except Exception:  # noqa: BLE001 - recorded, surfaced through /health/details and metrics
                self.write_failures += 1
                logger.exception("persistence.write_failed", extra={"operation": what})
                return None

        task = asyncio.ensure_future(_run())
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)
        return await asyncio.shield(task)

    async def drain(self, timeout: float = 10.0) -> None:
        if self._inflight:
            await asyncio.wait(list(self._inflight), timeout=timeout)


def describe(value: Any) -> str:
    return type(value).__name__
