"""User preferences (Settings page). Stored per account (or one local profile when auth is off)."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LanguagePreference = Literal["auto", "en", "hinglish", "hi"]


class UserPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # How Kamlesh Bhai addresses you ("Arey Kartik bhai!"). Empty = just "bhai".
    display_name: str = Field(default="", max_length=40)
    # Reply language. "auto" matches the language of each message.
    language: LanguagePreference = "auto"
    voice_input_enabled: bool = True
    voice_output_enabled: bool = True
    # Voice mode: send the final transcript automatically (no Execute click).
    voice_auto_submit: bool = True
    # Voice mode: start low-risk plans automatically (open, search, add to cart). Sensitive steps still need approval.
    voice_auto_execute: bool = True
    # Keep listening after Kamlesh Bhai answers (hands-free conversation).
    voice_continuous: bool = True
    speech_rate: float = Field(default=1.0, ge=0.5, le=1.5)
    preferred_store: Literal["none", "blinkit", "amazon"] = "none"

    @field_validator("display_name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        cleaned = re.sub(r"[^\w\s.'-]", "", value, flags=re.UNICODE).strip()
        return re.sub(r"\s+", " ", cleaned)[:40]


class PreferencesUpdate(BaseModel):
    """Partial update: only the fields sent are changed."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=40)
    language: LanguagePreference | None = None
    voice_input_enabled: bool | None = None
    voice_output_enabled: bool | None = None
    voice_auto_submit: bool | None = None
    voice_auto_execute: bool | None = None
    voice_continuous: bool | None = None
    speech_rate: float | None = Field(default=None, ge=0.5, le=1.5)
    preferred_store: Literal["none", "blinkit", "amazon"] | None = None
