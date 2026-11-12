"""Session ownership (dashboard session id -> user) and browser session metadata (never cookies)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, JsonType, UtcDateTime


class AppSessionRecord(Base):
    """Binds a client session id to exactly one user. A session id is never proof of access by itself."""

    __tablename__ = "app_sessions"
    __table_args__ = (Index("ix_app_sessions_user", "user_id"),)

    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class BrowserSessionRecord(Base):
    __tablename__ = "browser_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)  # = dashboard session id
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    persisted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
