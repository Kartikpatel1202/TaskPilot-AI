"""Append-only audit store with a SHA-256 hash chain (tamper-evident, not tamper-proof)."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.database.models import AuditEventRecord
from app.database.session import Database

GENESIS = "0" * 64


def chain_hash(prev_hash: str, fields: dict[str, Any]) -> str:
    canonical = json.dumps(fields, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256((prev_hash + canonical).encode()).hexdigest()


def hashed_fields(r: AuditEventRecord) -> dict[str, Any]:
    return {
        "event_id": str(r.event_id), "user_id": str(r.user_id) if r.user_id else None, "task_id": str(r.task_id) if r.task_id else None,
        "session_id": str(r.session_id) if r.session_id else None, "event_type": r.event_type, "outcome": r.outcome,
        "resource_type": r.resource_type, "resource_id": str(r.resource_id) if r.resource_id else None,
        "occurred_at": r.occurred_at.isoformat(), "correlation_id": str(r.correlation_id), "metadata": r.metadata_json,
    }


class AuditRepository:
    """Only `append`, reads and chain verification are exposed — there is no update or delete method."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def append(self, record: AuditEventRecord) -> AuditEventRecord:
        async with self.db.session() as s:
            if not self.db.is_sqlite:  # serialise appends so the chain never forks (SQLite already has one writer)
                from sqlalchemy import text

                await s.execute(text("SELECT pg_advisory_xact_lock(424242)"))
            last = await s.scalar(select(AuditEventRecord.hash).order_by(AuditEventRecord.seq.desc()).limit(1))
            record.prev_hash = last or GENESIS
            record.hash = chain_hash(record.prev_hash, hashed_fields(record))
            s.add(record)
        return record

    async def page(self, *, user_id: UUID | None, after_seq: int | None, limit: int, event_type: str | None = None) -> list[AuditEventRecord]:
        conds = []
        if user_id is not None:
            conds.append(AuditEventRecord.user_id == user_id)
        if event_type:
            conds.append(AuditEventRecord.event_type == event_type)
        if after_seq is not None:
            conds.append(AuditEventRecord.seq < after_seq)
        async with self.db.session() as s:
            rows = await s.scalars(select(AuditEventRecord).where(*conds).order_by(AuditEventRecord.seq.desc()).limit(limit))
            return list(rows)

    async def verify(self) -> tuple[bool, int, int | None]:
        """(intact, checked_count, first_broken_seq)."""
        prev = GENESIS
        checked = 0
        async with self.db.session() as s:
            rows = await s.scalars(select(AuditEventRecord).order_by(AuditEventRecord.seq))
            for r in rows:
                if r.prev_hash != prev or chain_hash(prev, hashed_fields(r)) != r.hash:
                    return False, checked, r.seq
                prev = r.hash
                checked += 1
        return True, checked, None
