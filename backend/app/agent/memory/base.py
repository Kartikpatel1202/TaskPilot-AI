"""Memory store interface (in-memory today; a database-backed store can implement it later)."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.schemas.intent import IntentClassification, IntentType
from app.schemas.memory import ConversationTurn, PlanningContext


class MemoryStore(Protocol):
    def add_user_turn(self, session_id: UUID, task_id: UUID | None, content: str) -> ConversationTurn: ...

    def add_assistant_turn(
        self, session_id: UUID, task_id: UUID | None, content: str, intent: IntentType | None = None
    ) -> ConversationTurn: ...

    def build_context(self, session_id: UUID, task_id: UUID | None = None) -> PlanningContext: ...

    def remember_classification(self, session_id: UUID, task_id: UUID, classification: IntentClassification) -> None: ...

    def turns(self, session_id: UUID) -> list[ConversationTurn]: ...

    def prune_expired(self) -> int: ...
