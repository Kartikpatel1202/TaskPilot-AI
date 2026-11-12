"""Deterministic pre-screen for clearly disallowed requests.

A small, conservative list of obvious prompt-injection and abuse patterns that are
rejected before any LLM call. It is defence in depth, not the main classifier:
the system prompt, strict schemas, plan validation and URL policy still apply to
everything that passes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "PROMPT_INJECTION",
        re.compile(
            r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|prompts?)|"
            r"(reveal|show|print|leak) (me )?(your |the )?(system prompt|instructions|api[ _-]?keys?|secrets?)|"
            r"\b(developer|god|dan) mode\b|\bjailbreak\b",
            re.IGNORECASE,
        ),
    ),
    (
        "SECRET_ACCESS",
        re.compile(
            r"\b(api[ _-]?key|secret key|access token|environment variables?|\.env file|server files?|"
            r"/etc/passwd)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "CODE_EXECUTION",
        re.compile(
            r"\b(rm -rf|sudo|powershell|cmd\.exe|bash -c|eval\(|exec\(|os\.system|subprocess)\b|"
            r"\b(run|execute) (a |this |some )?(shell|bash|python|javascript|js|code|script|command)s?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "CROSS_SESSION",
        re.compile(r"\b(other|another|all) (users?|sessions?)'?s? (data|memory|history|conversations?)\b", re.IGNORECASE),
    ),
    (
        "HARMFUL",
        re.compile(
            r"\bhack(ing)? (into|someone)|\bsteal\b|crack (the |a |his |her )?password|"
            r"bypass (the )?(otp|captcha|2fa|two[- ]factor)|\bphishing\b|\bddos\b",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    category: str | None = None


def screen_request(text: str) -> GuardResult:
    for category, pattern in _RULES:
        if pattern.search(text):
            return GuardResult(allowed=False, category=category)
    return GuardResult(allowed=True)
