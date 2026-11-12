"""Validated plans (structured JSON only — never model reasoning text)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, JsonType, UtcDateTime


class PlanRecord(Base):
    __tablename__ = "plans"
    __table_args__ = (Index("ix_plans_task_created", "task_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    schema_version: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    # PlanningRecord context needed to re-plan after a restart (redacted command + clarifications).
    command: Mapped[str | None] = mapped_column(Text)
    clarifications_json: Mapped[list[Any] | None] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
