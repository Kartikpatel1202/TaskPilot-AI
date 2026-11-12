"""Command normalisation: safe, deterministic clean-up before any LLM sees the text."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.core.logging import redact_text
from app.core.persona import Language, detect_language

_WAKE_WORD = re.compile(
    r"^\s*(?:(?:hey|hi|ok|okay|arre|are|oye)\s+)?(?:kamlesh\s*bhai|कमलेश\s*भाई)\s*[,!:.\-–—]*\s*",
    re.IGNORECASE,
)
_CONTROL = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\u200b-\u200f\u2028-\u202e\u2060-\u206f]")
_SPACES = re.compile(r"[ \t]+")


@dataclass(frozen=True)
class NormalizedCommand:
    original: str
    normalized: str
    language: Language
    was_redacted: bool


def normalize_command(text: str, max_length: int = 4000) -> NormalizedCommand:
    """NFC-normalise, strip control/bidi characters and the wake word, redact secrets.

    The original text is preserved for the record; only `normalized` goes to the LLM.
    """
    cleaned = unicodedata.normalize("NFC", text)
    cleaned = _CONTROL.sub("", cleaned)
    cleaned = _SPACES.sub(" ", cleaned).strip()
    without_wake = _WAKE_WORD.sub("", cleaned, count=1).strip() or cleaned
    redacted = redact_text(without_wake)[:max_length]
    return NormalizedCommand(
        original=text,
        normalized=redacted,
        language=detect_language(redacted),
        was_redacted=redacted != without_wake[:max_length],
    )
