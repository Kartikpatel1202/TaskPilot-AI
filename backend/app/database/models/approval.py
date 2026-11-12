"""Approvals with optimistic versioning and one-time-use tracking."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, JsonType, UtcDateTime


class ApprovalRecord(Base):
    __tablename__ = "approvals"
    __table_args__ = (Index("ix_approvals_task", "task_id"), Index("ix_approvals_status_expires", "status", "expires_at"))

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)  # generic | purchase | calendar
    step_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    snapshot_hash: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    decision: Mapped[str | None] = mapped_column(String(16))
    used_at: Mapped[datetime | None] = mapped_column(UtcDateTime)  # consumed exactly once
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
