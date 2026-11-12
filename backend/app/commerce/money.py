"""INR amounts as Decimal. Never float."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_AMOUNT = re.compile(r"(?:₹|rs\.?|inr)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.IGNORECASE)
_BARE = re.compile(r"^\s*-?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*$")
CENT = Decimal("0.01")


def parse_inr(text: str | None) -> Decimal | None:
    """First rupee amount in `text` ("₹1,23,456.50", "Rs. 54", "INR 99") — None if absent."""
    if not text:
        return None
    match = _AMOUNT.search(text) or _BARE.match(text)
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(",", "")).quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def parse_all_inr(text: str | None) -> list[Decimal]:
    if not text:
        return []
    out: list[Decimal] = []
    for m in _AMOUNT.finditer(text):
        try:
            out.append(Decimal(m.group(1).replace(",", "")).quantize(CENT, rounding=ROUND_HALF_UP))
        except InvalidOperation:
            continue
    return out


def is_free(text: str | None) -> bool:
    return bool(text and re.search(r"\bfree\b", text, re.IGNORECASE))


def format_inr(value: Decimal | None) -> str:
    if value is None:
        return "Not available"
    sign = "-" if value < 0 else ""
    value = abs(value).quantize(CENT)
    whole, frac = f"{value:.2f}".split(".")
    # Indian grouping: last 3 digits, then pairs.
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    return f"{sign}₹{whole}.{frac}"


def percent_change(previous: Decimal, current: Decimal) -> Decimal:
    if previous == 0:
        return Decimal("100") if current != 0 else Decimal("0")
    return ((current - previous) / previous * 100).quantize(CENT, rounding=ROUND_HALF_UP)
