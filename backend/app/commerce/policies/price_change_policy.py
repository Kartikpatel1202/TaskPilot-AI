"""Price-change detection. Every change is disclosed; none is ever silently accepted.

COMMERCE_MAX_PRICE_CHANGE_PERCENT only decides whether a change is flagged as
*significant* (an extra warning). Any change between approval and submission makes the
approval stale regardless of size (enforced by the summary hash in purchase_policy).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.commerce.money import format_inr, percent_change


@dataclass(frozen=True)
class PriceChange:
    label: str
    previous: Decimal
    current: Decimal
    difference: Decimal
    percent: Decimal
    significant: bool

    def message(self) -> str:
        direction = "increased" if self.difference > 0 else "decreased"
        note = " — significant change" if self.significant else ""
        return (
            f"{self.label}: price {direction} from {format_inr(self.previous)} to {format_inr(self.current)} "
            f"({'+' if self.difference > 0 else ''}{format_inr(self.difference)}, {self.percent}%){note}."
        )


class PriceChangePolicy:
    def __init__(self, max_change_percent: float) -> None:
        self._max = Decimal(str(max_change_percent))

    def compare(self, label: str, previous: Decimal | None, current: Decimal | None) -> PriceChange | None:
        """None when either value is unknown or the price is unchanged."""
        if previous is None or current is None or previous == current:
            return None
        pct = percent_change(previous, current)
        return PriceChange(label, previous, current, current - previous, pct, abs(pct) > self._max)
