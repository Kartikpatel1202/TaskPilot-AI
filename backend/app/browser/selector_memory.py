"""SelectorMemory: verified target METADATA (never live Locator objects), with expiry.

Keyed by (domain, page context, semantic target, role). Every reuse is revalidated against the fresh
DOM by the resolver; an entry is a hint, never proof that the element still exists.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass


@dataclass(frozen=True)
class SelectorEntry:
    role: str | None
    accessible_name: str | None
    stable_attributes: tuple[tuple[str, str], ...]
    verified_at: float


class SelectorMemory:
    def __init__(self, *, ttl_seconds: float = 1800, max_entries: int = 512) -> None:
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[tuple[str, ...], SelectorEntry] = OrderedDict()

    def get(self, key: tuple[str, ...]) -> SelectorEntry | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if time.monotonic() - entry.verified_at > self.ttl:
            self._entries.pop(key, None)
            return None
        return entry

    def remember(self, key: tuple[str, ...], role: str | None, name: str | None, stable: dict[str, str] | None = None) -> None:
        self._entries[key] = SelectorEntry(role, name, tuple(sorted((stable or {}).items())), time.monotonic())
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def forget(self, key: tuple[str, ...]) -> None:
        self._entries.pop(key, None)

    def __len__(self) -> int:
        return len(self._entries)
