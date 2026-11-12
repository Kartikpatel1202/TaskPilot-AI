"""Tasks (commands are stored redacted: card numbers, OTPs, passwords and tokens are masked)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, UtcDateTime


class TaskRecord(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_user_created", "user_id", "created_at"),
        Index("ix_tasks_session_created", "session_id", "created_at"),
        Index("ix_tasks_state", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    input_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(1000))
    execution_status: Mapped[str | None] = mapped_column(String(32))
    recovery_note: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
