"""Session-isolated, bounded, expiring conversation memory (in process memory only).

* Keyed strictly by session id — there is no API to read another session.
* Content is redacted (cards, OTPs, passwords, tokens) before it is stored.
* Bounded per session (turns + characters) and across sessions (LRU), with TTL expiry.
* Not persistent: a backend restart clears it. Database-backed memory is a future phase.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from app.agent.websites import normalize_website
from app.core.logging import redact_text
from app.schemas.common import utc_now
from app.schemas.intent import IntentClassification, IntentType
from app.schemas.memory import (
    ContextTurn,
    ConversationRole,
    ConversationTurn,
    PlanningContext,
)

from .conversation_memory import ConversationMemory

_CONTEXT_INTENTS = {
    IntentType.ECOMMERCE_SHOPPING,
    IntentType.ECOMMERCE_SEARCH,
    IntentType.MEDIA_SEARCH,
    IntentType.EMAIL_DRAFT,
    IntentType.EMAIL_SEND,
    IntentType.CALENDAR_MANAGEMENT,
    IntentType.BROWSER_NAVIGATION,
    IntentType.DATA_EXTRACTION,
}


class MemoryManager:
    def __init__(
        self,
        *,
        max_turns: int,
        max_characters: int,
        ttl_minutes: int,
        max_sessions: int,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._max_turns = max_turns
        self._max_characters = max_characters
        self._ttl = timedelta(minutes=ttl_minutes)
        self._max_sessions = max_sessions
        self._clock = clock
        self._sessions: OrderedDict[UUID, ConversationMemory] = OrderedDict()

    # ---------------------------------------------------------------- session access

    def _session(self, session_id: UUID, *, create: bool = True) -> ConversationMemory | None:
        now = self._clock()
        memory = self._sessions.get(session_id)
        if memory is not None and now - memory.last_access > self._ttl:
            del self._sessions[session_id]  # expired
            memory = None
        if memory is None:
            if not create:
                return None
            memory = ConversationMemory(max_turns=self._max_turns, max_characters=self._max_characters, now=now)
            self._sessions[session_id] = memory
            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)
        else:
            self._sessions.move_to_end(session_id)
        memory.last_access = now
        return memory

    def has_session(self, session_id: UUID) -> bool:
        return self._session(session_id, create=False) is not None

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    def prune_expired(self) -> int:
        now = self._clock()
        expired = [sid for sid, mem in self._sessions.items() if now - mem.last_access > self._ttl]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)

    def clear_session(self, session_id: UUID) -> None:
        self._sessions.pop(session_id, None)

    # ---------------------------------------------------------------- turns

    def _add(self, session_id: UUID, task_id: UUID | None, role: ConversationRole, content: str, intent: IntentType | None) -> ConversationTurn:
        memory = self._session(session_id)
        assert memory is not None
        turn = ConversationTurn(
            turn_id=uuid4(),
            session_id=session_id,
            task_id=task_id,
            role=role,
            content=redact_text(content.strip())[: self._max_characters],
            intent=intent,
            created_at=self._clock(),
        )
        memory.add(turn)
        return turn

    def add_user_turn(self, session_id: UUID, task_id: UUID | None, content: str) -> ConversationTurn:
        return self._add(session_id, task_id, ConversationRole.USER, content, None)

    def add_assistant_turn(
        self, session_id: UUID, task_id: UUID | None, content: str, intent: IntentType | None = None
    ) -> ConversationTurn:
        return self._add(session_id, task_id, ConversationRole.ASSISTANT, content, intent)

    def turns(self, session_id: UUID) -> list[ConversationTurn]:
        memory = self._session(session_id, create=False)
        return list(memory.turns) if memory else []

    # ---------------------------------------------------------------- context

    def build_context(self, session_id: UUID, task_id: UUID | None = None, budget: int | None = None) -> PlanningContext:
        """Recent turns within a character budget, current-task turns first, chronological order."""
        memory = self._session(session_id, create=False)
        if memory is None:
            return PlanningContext()
        budget = budget or self._max_characters // 2
        turns = list(memory.turns)
        chosen: set[UUID] = set()
        used = 0
        prioritised = [t for t in reversed(turns) if task_id is not None and t.task_id == task_id] + [
            t for t in reversed(turns) if task_id is None or t.task_id != task_id
        ]
        for turn in prioritised:
            if used + len(turn.content) > budget:
                continue
            chosen.add(turn.turn_id)
            used += len(turn.content)
        recent = [ContextTurn(role=t.role, content=t.content, intent=t.intent) for t in turns if t.turn_id in chosen]
        return PlanningContext(summary=memory.summary, recent_turns=recent, session_context=memory.context.model_copy(deep=True))

    def remember_classification(self, session_id: UUID, task_id: UUID, classification: IntentClassification) -> None:
        """Carry website/products forward so follow-ups ("add one bread too") resolve."""
        memory = self._session(session_id)
        assert memory is not None
        ctx = memory.context
        website = normalize_website(classification.target_website)
        if classification.intent == IntentType.GENERAL_CHAT:
            if website:
                ctx.active_website = website
            return
        if classification.intent not in _CONTEXT_INTENTS:
            return
        if website:
            if ctx.active_website and website != ctx.active_website and not classification.is_follow_up:
                ctx.products = []  # new store, new basket
            ctx.active_website = website
        ctx.active_intent = classification.intent
        if classification.entities.products:
            ctx.products = [p.model_copy() for p in classification.entities.products]
        elif not classification.is_follow_up and classification.intent != IntentType.ECOMMERCE_SHOPPING:
            ctx.products = []
        ctx.last_task_id = task_id
