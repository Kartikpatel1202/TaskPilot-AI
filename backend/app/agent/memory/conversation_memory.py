"""One session's bounded conversation memory."""

from __future__ import annotations

from collections import deque
from datetime import datetime

from app.schemas.memory import ConversationTurn, SessionContext

from .summarizer import summarize_turns


class ConversationMemory:
    def __init__(self, *, max_turns: int, max_characters: int, now: datetime) -> None:
        self._max_turns = max_turns
        self._max_characters = max_characters
        self.turns: deque[ConversationTurn] = deque()
        self.summary: str | None = None
        self.context = SessionContext()
        self.last_access = now

    @property
    def characters(self) -> int:
        return sum(len(t.content) for t in self.turns) + len(self.summary or "")

    def add(self, turn: ConversationTurn) -> None:
        self.turns.append(turn)
        self._enforce_limits()

    def _enforce_limits(self) -> None:
        evicted: list[ConversationTurn] = []
        while len(self.turns) > self._max_turns:
            evicted.append(self.turns.popleft())
        while len(self.turns) > 1 and sum(len(t.content) for t in self.turns) > self._max_characters * 0.8:
            evicted.append(self.turns.popleft())
        if evicted:
            self.summary = summarize_turns(evicted, self.summary)
        # Final hard cap (e.g. one huge turn): truncate the newest turn's content.
        if self.characters > self._max_characters and self.turns:
            overflow = self.characters - self._max_characters
            last = self.turns[-1]
            self.turns[-1] = last.model_copy(update={"content": last.content[: max(0, len(last.content) - overflow)]})
