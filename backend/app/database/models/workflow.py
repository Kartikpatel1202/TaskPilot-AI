"""Multi-domain workflow state (observed results; no bodies, cookies or paths)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, JsonType, UtcDateTime


class WorkflowRecord(Base):
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    domains: Mapped[list[str]] = mapped_column(JsonType, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    state_json: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
