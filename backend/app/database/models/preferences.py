"""Per-account preferences (Settings page)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, JsonType, UtcDateTime


class UserPreferencesRecord(Base):
    __tablename__ = "user_preferences"

    # The user id, or "local" for the single development profile when authentication is off.
    owner_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
