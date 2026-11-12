"""Integration interfaces for later phases.

Phase 1 deliberately ships NO implementations of these. They exist so that
Phase 2 (LLM planner) and Phase 3 (Playwright browser controller) can plug in
without changing the task service, telemetry protocol or UI contracts.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.schemas.task import Task


@runtime_checkable
class TaskPlanner(Protocol):
    """Phase 2: turns a natural-language command into an execution plan."""

    async def plan(self, task: Task) -> None: ...


@runtime_checkable
class BrowserController(Protocol):
    """Phase 3: drives a real browser and streams frames as `browser.preview` events."""

    async def start(self, task: Task) -> None: ...

    async def stop(self, task: Task) -> None: ...
