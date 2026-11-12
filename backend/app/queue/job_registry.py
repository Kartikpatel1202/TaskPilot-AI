"""Job kind -> async handler. Unknown kinds are dead-lettered, never guessed."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

Handler = Callable[[dict[str, Any]], Awaitable[None]]


class JobRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, kind: str, handler: Handler) -> None:
        if kind in self._handlers:
            raise ValueError(f"Job kind {kind!r} is already registered.")
        self._handlers[kind] = handler

    def get(self, kind: str) -> Handler | None:
        return self._handlers.get(kind)

    def kinds(self) -> list[str]:
        return sorted(self._handlers)
