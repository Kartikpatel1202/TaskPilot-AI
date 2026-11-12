"""Optional encrypted persistence of Playwright storage state (cookies/localStorage).

Off by default (BROWSER_PERSIST_SESSIONS=false). When enabled, state is encrypted
with Fernet (AES-128-CBC + HMAC) before touching disk; plaintext cookies or tokens
are never written. One file per TaskPilot session, named by a hash of the id.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

from app.core.logging import get_logger

logger = get_logger("browser.store")


class SessionStore:
    def __init__(self, directory: str | Path, key: str, ttl: timedelta) -> None:
        self._dir = Path(directory)
        self._fernet = Fernet(key.encode())
        self._ttl = ttl

    def _path(self, session_id: UUID) -> Path:
        name = hashlib.sha256(str(session_id).encode()).hexdigest()
        return self._dir / f"{name}.state.enc"

    def save(self, session_id: UUID, state: dict[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self._dir, 0o700)
        except OSError:
            pass
        payload = json.dumps(
            {"session_id": str(session_id), "saved_at": datetime.now(timezone.utc).isoformat(), "state": state}
        ).encode()
        path = self._path(session_id)
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(self._fernet.encrypt(payload))
        os.replace(tmp, path)
        logger.info("browser.state_saved", extra={"session": str(session_id)[:8]})

    def load(self, session_id: UUID) -> dict[str, Any] | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(self._fernet.decrypt(path.read_bytes()))
        except (InvalidToken, ValueError):
            logger.warning("browser.state_unreadable", extra={"session": str(session_id)[:8]})
            self.delete(session_id)
            return None
        if data.get("session_id") != str(session_id):
            return None  # never restore another session's state
        saved_at = datetime.fromisoformat(data["saved_at"])
        if datetime.now(timezone.utc) - saved_at > self._ttl:
            self.delete(session_id)
            return None
        state = data.get("state")
        return state if isinstance(state, dict) else None

    def delete(self, session_id: UUID) -> None:
        try:
            self._path(session_id).unlink(missing_ok=True)
        except OSError:
            pass

    def purge_expired(self) -> int:
        if not self._dir.exists():
            return 0
        removed = 0
        cutoff = datetime.now(timezone.utc) - self._ttl
        for path in self._dir.glob("*.state.enc"):
            try:
                if datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
        return removed
