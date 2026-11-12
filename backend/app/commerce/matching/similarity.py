"""Text similarity and quantity/unit normalisation for product matching.

1 L = 1000 ml, 1 kg = 1000 g, 1 dozen = 12 pieces. Pack sizes are read from
observed text ("2 x 500 ml", "Pack of 6", "12 pcs"). When a size cannot be
read unambiguously, the result is `None` — never a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from app.schemas.product import ProductRequirement, ProductUnit

_SYNONYMS = {
    "doodh": "milk", "dudh": "milk", "दूध": "milk", "anda": "egg", "ande": "egg", "eggs": "egg", "अंडे": "egg",
    "breads": "bread", "ब्रेड": "bread", "kela": "banana", "kele": "banana", "bananas": "banana",
    "apples": "apple", "seb": "apple", "pyaz": "onion", "pyaaz": "onion", "onions": "onion",
    "tamatar": "tomato", "tomatoes": "tomato", "dahi": "curd", "laptops": "laptop", "phones": "phone",
    "mobile": "phone", "smartphone": "phone", "headphone": "headphones", "earphones": "headphones",
    "mice": "mouse", "keyboards": "keyboard", "taza": "taaza", "fresh": "fresh",
}
_STOP = {
    "the", "a", "an", "of", "for", "with", "and", "in", "pack", "packet", "pouch", "bottle", "tetra", "fresh",
    "ka", "ki", "ke", "wala", "wali", "x", "pcs", "pc", "piece", "pieces", "l", "ml", "kg", "g", "gm", "litre",
    "liter", "ltr", "dozen", "by", "new",
}
_MEASURE_TOKEN = re.compile(r"^\d+(\.\d+)?(l|ml|kg|g|gm|gb|tb|pcs|pc)?$")


def norm_token(token: str) -> str:
    t = token.lower().strip(".,()[]-/'\"")
    return _SYNONYMS.get(t, t)


def tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    raw = re.findall(r"[a-zA-Zऀ-ॿ]+|\d+(?:\.\d+)?[a-zA-Z]*", text.lower())
    return {norm_token(t) for t in raw if norm_token(t) and norm_token(t) not in _STOP and not _MEASURE_TOKEN.match(t)}


# Category words that listings rarely spell out ("Samsung Galaxy M34 5G" is a phone).
CATEGORY_ALIASES: dict[str, frozenset[str]] = {
    "phone": frozenset({"smartphone", "mobile", "galaxy", "iphone", "pixel", "redmi", "oneplus", "5g", "realme", "vivo", "oppo"}),
    "laptop": frozenset({"notebook", "vivobook", "ideapad", "thinkpad", "macbook", "chromebook", "zenbook", "inspiron", "pavilion", "aspire"}),
    "headphones": frozenset({"earbuds", "headset", "earphones", "tws", "neckband"}),
    "egg": frozenset({"eggs"}),
}


def _hit(word: str, have: set[str]) -> bool:
    if word in have or (word.endswith("s") and word[:-1] in have) or word + "s" in have:
        return True
    return bool(CATEGORY_ALIASES.get(word, frozenset()) & have)


def coverage(wanted: set[str], have: set[str]) -> float:
    if not wanted:
        return 1.0
    return sum(1 for w in wanted if _hit(w, have)) / len(wanted)


def family_key(name: str) -> str:
    """Product identity without its size ("Amul Taaza Toned Milk 1 L" -> "amul milk taaza toned")."""
    return " ".join(sorted(tokens(name)))


# ---------------------------------------------------------------------- measures

_TO_BASE = {
    "ml": ("ml", Decimal(1)), "l": ("ml", Decimal(1000)), "ltr": ("ml", Decimal(1000)), "litre": ("ml", Decimal(1000)),
    "liter": ("ml", Decimal(1000)), "litres": ("ml", Decimal(1000)), "liters": ("ml", Decimal(1000)),
    "g": ("g", Decimal(1)), "gm": ("g", Decimal(1)), "gms": ("g", Decimal(1)), "gram": ("g", Decimal(1)),
    "grams": ("g", Decimal(1)), "kg": ("g", Decimal(1000)), "kilo": ("g", Decimal(1000)),
    "pc": ("pc", Decimal(1)), "pcs": ("pc", Decimal(1)), "piece": ("pc", Decimal(1)), "pieces": ("pc", Decimal(1)),
    "eggs": ("pc", Decimal(1)), "units": ("pc", Decimal(1)), "unit": ("pc", Decimal(1)), "dozen": ("pc", Decimal(12)),
}
_UNIT_RE = r"(ml|ltr|litres?|liters?|l|kg|kilo|gms?|grams?|g|pcs|pc|pieces?|eggs|units?|dozen)"
_MULTI = re.compile(rf"(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*{_UNIT_RE}\b", re.IGNORECASE)
_SINGLE = re.compile(rf"(\d+(?:\.\d+)?)\s*{_UNIT_RE}\b", re.IGNORECASE)
_PACK_OF = re.compile(r"\bpack\s+of\s+(\d+)\b|\b(\d+)\s*(?:packs?|pkts?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Measure:
    """Amount sold per unit of sale (one cart quantity), in a base unit."""

    amount: Decimal
    base: str  # ml | g | pc | pack
    text: str

    def describe(self) -> str:
        def num(value: Decimal) -> str:
            return format(value.normalize(), "f")

        if self.base == "ml":
            return f"{num(self.amount / 1000)} L" if self.amount >= 1000 else f"{num(self.amount)} ml"
        if self.base == "g":
            return f"{num(self.amount / 1000)} kg" if self.amount >= 1000 else f"{num(self.amount)} g"
        if self.base == "pack":
            return f"{num(self.amount)} pack" + ("s" if self.amount != 1 else "")
        return f"{num(self.amount)} pcs"


def parse_measure(*texts: str | None) -> Measure | None:
    """Pack size from observed text. Multipacks ("2 x 500 ml") count as their total."""
    blob = " ".join(t for t in texts if t)
    if not blob:
        return None
    m = _MULTI.search(blob)
    if m:
        base, factor = _TO_BASE[m.group(3).lower()]
        return Measure(Decimal(m.group(1)) * Decimal(m.group(2)) * factor, base, m.group(0))
    m = _SINGLE.search(blob)
    if m:
        base, factor = _TO_BASE[m.group(2).lower()]
        amount = Decimal(m.group(1)) * factor
        pack = _PACK_OF.search(blob)
        if pack and base != "pc":
            amount *= Decimal(pack.group(1) or pack.group(2))
        return Measure(amount, base, m.group(0))
    pack = _PACK_OF.search(blob)
    if pack:
        return Measure(Decimal(pack.group(1) or pack.group(2)), "pc", pack.group(0))
    return None


def requirement_measure(req: ProductRequirement) -> Measure | None:
    """Total requested amount in a base unit (None for packs/unknown units)."""
    qty = Decimal(str(req.quantity))
    conv = {
        ProductUnit.LITER: ("ml", Decimal(1000)), ProductUnit.MILLILITER: ("ml", Decimal(1)),
        ProductUnit.KILOGRAM: ("g", Decimal(1000)), ProductUnit.GRAM: ("g", Decimal(1)),
        ProductUnit.DOZEN: ("pc", Decimal(12)), ProductUnit.PIECE: ("pc", Decimal(1)),
    }.get(req.unit)
    if conv is None:
        return None
    return Measure(qty * conv[1], conv[0], req.label())


def packs_for(requested: Measure, offered: Measure, max_packs: int) -> int | None:
    """How many identical packs make exactly the requested amount (None if not exact or too many)."""
    if requested.base != offered.base or offered.amount <= 0:
        return None
    ratio = requested.amount / offered.amount
    if ratio != ratio.to_integral_value() or ratio < 1:
        return None
    count = int(ratio)
    return count if count <= max_packs else None
