"""Deterministic product matching: brand, variant, quantity/units, multipacks, ambiguity, budget."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.commerce.matching.product_matcher import MatchThresholds, ProductMatcher
from app.commerce.matching.similarity import Measure, packs_for, parse_measure, requirement_measure
from app.commerce.matching.variant_matcher import check_variant, extract_specs
from app.commerce.money import format_inr, parse_inr
from app.schemas.product import MatchDecision

from .conftest import cand, req

M = ProductMatcher()
MILK = [
    cand("Amul Taaza Toned Milk", "1 L", "56", brand="Amul"),
    cand("Amul Gold Full Cream Milk", "1 L", "68", brand="Amul"),
    cand("Mother Dairy Toned Milk", "1 L", "56", brand="Mother Dairy"),
    cand("Amul Taaza Toned Milk", "500 ml", "28", brand="Amul"),
]


def by_name(result, name: str, size: str):  # type: ignore[no-untyped-def]
    ids = {c.candidate_id: c for c in MILK}
    return next(m for m in result.ranked if ids[m.candidate_id].product_name == name and ids[m.candidate_id].pack_size == size)


def test_exact_brand_variant_and_quantity_is_selected_with_fewest_packs() -> None:
    r = M.match(req("milk", brand="Amul", qty=2, unit="LITER", variant="taaza"), MILK)
    assert r.decision == MatchDecision.SELECTED
    chosen = next(c for c in MILK if c.candidate_id == r.selected.candidate_id)
    assert (chosen.product_name, chosen.pack_size) == ("Amul Taaza Toned Milk", "1 L")
    assert r.selected.packs_needed == 2 and r.selected.exact_match


def test_wrong_variant_and_wrong_brand_are_disqualified() -> None:
    r = M.match(req("milk", brand="Amul", qty=2, unit="LITER", variant="taaza"), MILK)
    gold = by_name(r, "Amul Gold Full Cream Milk", "1 L")
    mother = by_name(r, "Mother Dairy Toned Milk", "1 L")
    assert gold.disqualified and "gold" in gold.explanation.lower()
    assert mother.disqualified and "brand" in mother.explanation.lower()
    assert all(m.overall_score <= 0.4 for m in (gold, mother))


def test_brand_mandatory_never_ranks_wrong_brand_above_exact_brand() -> None:
    r = M.match(req("milk", brand="Amul", qty=1, unit="LITER"), MILK)
    top_ids = [m.candidate_id for m in r.ranked[:2]]
    names = {c.candidate_id: c.product_name for c in MILK}
    assert all(names[i].startswith("Amul") for i in top_ids)


def test_ambiguous_without_variant_asks_the_user() -> None:
    r = M.match(req("milk", brand="Amul", qty=1, unit="LITER"), MILK)
    assert r.decision == MatchDecision.AMBIGUOUS


def test_multipack_and_unit_conversion() -> None:
    eggs = [cand("Farm Fresh White Eggs", "6 pieces", "52"), cand("Farm Fresh White Eggs", "12 pieces", "96")]
    r = M.match(req("eggs", qty=12, unit="PIECE"), eggs)
    assert r.decision == MatchDecision.SELECTED and r.selected.packs_needed == 1  # single 12-pack beats 2 × 6
    only_six = M.match(req("eggs", qty=12, unit="PIECE"), [eggs[0]])
    assert only_six.selected and only_six.selected.packs_needed == 2  # 2 × 6 = 12 when no 12-pack is offered


def test_incompatible_size_is_not_selected() -> None:
    r = M.match(req("milk", brand="Amul", qty=750, unit="MILLILITER", variant="taaza"), [MILK[0]])
    assert r.decision == MatchDecision.NOT_FOUND and r.ranked[0].disqualified


def test_unavailable_product_is_reported_as_unavailable() -> None:
    r = M.match(req("paneer", brand="Amul", qty=200, unit="GRAM"), [cand("Amul Malai Paneer", "200 g", "90", available=False)])
    assert r.decision == MatchDecision.UNAVAILABLE


def test_low_confidence_is_not_selected() -> None:
    r = M.match(req("headphones", brand="Sony"), [cand("Generic USB Cable", "1 m", "199")])
    assert r.decision == MatchDecision.NOT_FOUND


def test_specs_and_budget_filter_laptops() -> None:
    laptops = [
        cand("ASUS Vivobook 15 (16GB RAM/512GB SSD) Laptop", None, "54990"),
        cand("HP 15s (8GB RAM/512GB SSD) Laptop", None, "47990"),
        cand("Lenovo IdeaPad (16GB RAM/512GB SSD) Laptop", None, "62490"),
    ]
    r = M.match(req("laptop", qty=1, unit="UNKNOWN", specs={"RAM": "16GB", "STORAGE": "512GB"}, max_price=60000), laptops)
    names = {c.candidate_id: c.product_name for c in laptops}
    ok = [names[m.candidate_id] for m in r.ranked if not m.disqualified]
    assert ok == ["ASUS Vivobook 15 (16GB RAM/512GB SSD) Laptop"]
    assert r.decision == MatchDecision.SELECTED


def test_similar_title_with_other_ram_is_never_selected() -> None:
    r = M.match(req("laptop", qty=1, unit="UNKNOWN", specs={"RAM": "16GB"}), [cand("HP 15s (8GB RAM/512GB SSD) Laptop", None, "47990")])
    assert r.decision == MatchDecision.NOT_FOUND


def test_unverifiable_variant_needs_confirmation() -> None:
    r = M.match(req("phone", brand="Samsung", specs={"STORAGE": "256GB"}, unit="UNKNOWN"), [cand("Samsung Galaxy Phone", None, "19999")])
    assert r.decision == MatchDecision.NEEDS_CONFIRMATION and r.selected and r.selected.needs_user_confirmation


@pytest.mark.parametrize(("text", "amount", "base"), [
    ("1 L", 1000, "ml"), ("500 ml", 500, "ml"), ("1 ltr", 1000, "ml"), ("2 x 500 ml", 1000, "ml"), ("1 kg", 1000, "g"),
    ("400 g", 400, "g"), ("12 pieces", 12, "pc"), ("Pack of 6", 6, "pc"), ("1 dozen", 12, "pc"),
])
def test_parse_measure(text: str, amount: int, base: str) -> None:
    m = parse_measure(text)
    assert m is not None and m.amount == amount and m.base == base


def test_requirement_measure_and_packs() -> None:
    assert requirement_measure(req("milk", qty=2, unit="LITER")).amount == 2000  # type: ignore[union-attr]
    assert requirement_measure(req("eggs", qty=1, unit="DOZEN")).amount == 12  # type: ignore[union-attr]
    assert requirement_measure(req("bread", qty=1, unit="PACK")) is None
    two_l = Measure(Decimal(2000), "ml", "2 L")
    assert packs_for(two_l, Measure(Decimal(500), "ml", ""), 6) == 4
    assert packs_for(two_l, Measure(Decimal(750), "ml", ""), 6) is None
    assert packs_for(two_l, Measure(Decimal(100), "ml", ""), 6) is None  # more packs than allowed


def test_variant_checks_and_spec_extraction() -> None:
    assert extract_specs("Laptop (16GB RAM/1TB SSD)") == {"RAM": "16GB", "STORAGE": "1024GB"}
    assert check_variant({}, {"line": "taaza"}, "Amul Gold Milk", {}).contradicted
    assert check_variant({}, {"line": "taaza"}, "Amul Taaza Milk", {}).score == 1.0
    assert check_variant({"COLOR": "black"}, {}, "Mouse", {}).unverified


def test_money_is_decimal_and_formatted_in_inr() -> None:
    assert parse_inr("₹1,23,456.50") == Decimal("123456.50")
    assert parse_inr("Rs. 54") == Decimal("54.00")
    assert parse_inr("FREE") is None
    assert format_inr(Decimal("123456.5")) == "₹1,23,456.50"
    assert format_inr(None) == "Not available"


def test_thresholds_are_configurable() -> None:
    strict = ProductMatcher(MatchThresholds(exact=0.99, acceptable=0.98, margin=0.05))
    r = strict.match(req("eggs", qty=12, unit="PIECE"), [cand("Farm Fresh White Eggs", "6 pieces", "52")])
    assert r.decision == MatchDecision.NOT_FOUND  # 2 packs scores below a 0.98 acceptance bar
