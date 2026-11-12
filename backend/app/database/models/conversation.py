"""Bounded, redacted conversation memory with expiry."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, UtcDateTime


class ConversationTurnRecord(Base):
    __tablename__ = "conversation_turns"
    __table_args__ = (Index("ix_conversation_session_created", "session_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)  # redacted
    intent: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
