"""Observed integration status per session, and LLM usage accounting (no prompts stored)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Float, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, UtcDateTime


class IntegrationStatusRecord(Base):
    __tablename__ = "integration_statuses"

    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    domain: Mapped[str] = mapped_column(String(24), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(String(300), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class LlmUsageRecord(Base):
    __tablename__ = "llm_usage"
    __table_args__ = (Index("ix_llm_usage_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    request_type: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
