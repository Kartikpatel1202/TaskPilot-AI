"""Price changes are always disclosed; the threshold only flags significance."""

from __future__ import annotations

from decimal import Decimal

from app.commerce.policies.price_change_policy import PriceChangePolicy

P = PriceChangePolicy(5)


def test_unchanged_or_unknown_prices_report_nothing() -> None:
    assert P.compare("Milk", Decimal("56"), Decimal("56")) is None
    assert P.compare("Milk", None, Decimal("56")) is None
    assert P.compare("Milk", Decimal("56"), None) is None


def test_small_change_is_disclosed_but_not_significant() -> None:
    change = P.compare("Milk", Decimal("100"), Decimal("102"))
    assert change is not None and not change.significant and change.difference == Decimal("2")
    assert "increased" in change.message() and "₹100.00" in change.message()


def test_large_change_is_significant() -> None:
    change = P.compare("Order total", Decimal("500"), Decimal("540"))
    assert change is not None and change.significant and change.percent == Decimal("8.00")
    assert "+₹40.00" in change.message()


def test_decreases_are_disclosed_too() -> None:
    change = P.compare("Milk", Decimal("60"), Decimal("56"))
    assert change is not None and "decreased" in change.message()
