"""Execution journal: one row per (task, plan, step, action version) — the idempotency identity."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, JsonType, UtcDateTime


class ActionLifecycle(str, Enum):
    PENDING = "PENDING"
    PREPARED = "PREPARED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class ActionJournalRecord(Base):
    __tablename__ = "action_journal"
    __table_args__ = (Index("ix_action_journal_task", "task_id", "step_order"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    step_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    action_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    mutating: Mapped[bool] = mapped_column(Boolean, nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error_code: Mapped[str | None] = mapped_column(String(80))
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JsonType)  # safe summary only
    worker_id: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
