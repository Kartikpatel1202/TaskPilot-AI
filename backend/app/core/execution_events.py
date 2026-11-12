"""Thin, failure-tolerant publisher for Phase 3 browser and execution telemetry.

Uses the existing EventManager/WebSocketManager (no second transport). Payloads
are typed Pydantic models; screenshots are never part of telemetry.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.core.event_manager import EventManager
from app.core.logging import get_logger
from app.schemas.telemetry import TelemetryEventType

logger = get_logger("execution.events")


class ExecutionEvents:
    def __init__(self, events: EventManager) -> None:
        self._events = events

    async def emit(
        self, session_id: UUID, event_type: TelemetryEventType, payload: BaseModel, task_id: UUID | None = None
    ) -> None:
        try:
            await self._events.emit(session_id, event_type, payload, task_id=task_id)
        except Exception:  # telemetry must never break browser execution
            logger.exception("telemetry.emit_failed", extra={"event_type": event_type.value})
