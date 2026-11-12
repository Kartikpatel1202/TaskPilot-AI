"""Variant/specification matching (RAM, storage, colour, product line such as "Taaza" vs "Gold").

A requested variant either matches, contradicts, or cannot be verified from the
observed text. Contradictions disqualify a candidate; unverifiable variants need
the user's confirmation. Nothing is assumed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.commerce.matching.similarity import tokens

# Mutually exclusive product lines: picking one when another was requested is a wrong variant.
VARIANT_FAMILIES: tuple[frozenset[str], ...] = (
    frozenset({"taaza", "gold", "slim", "shakti", "cow", "buffalo"}),  # milk lines
    frozenset({"toned", "double toned", "full cream", "skimmed"}),
    frozenset({"white", "brown", "multigrain", "whole wheat", "sandwich"}),  # bread
    frozenset({"black", "white", "blue", "red", "green", "silver", "grey", "gray", "gold", "pink", "purple"}),
)
COLORS = frozenset({"black", "white", "blue", "red", "green", "silver", "grey", "gray", "pink", "purple", "beige"})

_RAM = re.compile(r"(\d{1,3})\s*gb\s*(?:ram|ddr\d?|lpddr\d?x?|memory)\b|\b(?:ram)\s*[:\-]?\s*(\d{1,3})\s*gb", re.IGNORECASE)
_STORAGE = re.compile(
    r"(\d{1,4})\s*(gb|tb)\s*(?:ssd|hdd|storage|rom|emmc|nvme)\b|\b(?:ssd|storage|rom)\s*[:\-]?\s*(\d{1,4})\s*(gb|tb)",
    re.IGNORECASE,
)


def _gb(value: str, unit: str) -> int:
    return int(value) * (1024 if unit.lower() == "tb" else 1)


def extract_specs(*texts: str | None) -> dict[str, str]:
    blob = " ".join(t for t in texts if t)
    specs: dict[str, str] = {}
    if m := _RAM.search(blob):
        specs["RAM"] = f"{m.group(1) or m.group(2)}GB"
    if m := _STORAGE.search(blob):
        size = _gb(m.group(1) or m.group(3), m.group(2) or m.group(4))
        specs["STORAGE"] = f"{size}GB"
    words = tokens(blob)
    colors = sorted(COLORS & words)
    if len(colors) == 1:
        specs["COLOR"] = colors[0]
    return specs


def normalize_spec(key: str, value: str) -> tuple[str, str]:
    k = key.strip().upper()
    k = {"SSD": "STORAGE", "ROM": "STORAGE", "MEMORY": "RAM", "COLOUR": "COLOR"}.get(k, k)
    v = value.strip().upper().replace(" ", "")
    if k in ("RAM", "STORAGE"):
        m = re.match(r"(\d+)(GB|TB)?", v)
        if m:
            v = f"{_gb(m.group(1), m.group(2) or 'GB')}GB"
    return k, v.lower() if k == "COLOR" else v


@dataclass
class VariantCheck:
    score: float
    contradicted: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)


def check_variant(
    required_specs: dict[str, str],
    preferred_variant: dict[str, str],
    candidate_name: str,
    candidate_variant: dict[str, str],
) -> VariantCheck:
    observed = {normalize_spec(k, v)[0]: normalize_spec(k, v)[1] for k, v in candidate_variant.items()}
    for k, v in extract_specs(candidate_name, " ".join(f"{a} {b}" for a, b in candidate_variant.items())).items():
        observed.setdefault(k, v)
    name_words = tokens(candidate_name) | tokens(" ".join(candidate_variant.values()))
    low_name = candidate_name.lower()
    result = VariantCheck(score=1.0)
    wanted = [normalize_spec(k, v) for k, v in required_specs.items()]
    for key, value in wanted:
        seen = observed.get(key)
        label = f"{key} {value}"
        if seen is None:
            result.unverified.append(label)
        elif seen == value:
            result.matched.append(label)
        else:
            result.contradicted.append(f"{label} (listing shows {seen})")
    for value in preferred_variant.values():
        line = value.strip().lower()
        if not line:
            continue
        if line in low_name or set(line.split()) <= name_words:
            result.matched.append(line)
            continue
        family = next((f for f in VARIANT_FAMILIES if line in f), None)
        others = [o for o in (family or ()) if o != line and (o in name_words or o in low_name)]
        if others:
            result.contradicted.append(f"{line} requested, listing is {others[0]}")
        else:
            result.unverified.append(line)
    total = len(wanted) + len([v for v in preferred_variant.values() if v.strip()])
    if total == 0:
        return result
    if result.contradicted:
        result.score = 0.0
    else:
        result.score = round((len(result.matched) + 0.5 * len(result.unverified)) / total, 3)
    return result
