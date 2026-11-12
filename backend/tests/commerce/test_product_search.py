"""Search orchestration and result parsing: bounded attempts, nothing invented."""

from __future__ import annotations

from typing import Any

from app.commerce.base import CommerceContext
from app.commerce.search.product_search import search_with_retries
from app.commerce.search.result_parser import to_candidate, to_candidates
from app.schemas.product import CommercePlatform, ProductAvailability

from .conftest import cand, req


class FakeAdapter:
    def __init__(self, answers: list[list[Any]]) -> None:
        self.answers = answers
        self.calls = 0

    async def search_products(self, requirement: Any, ctx: Any) -> list[Any]:
        self.calls += 1
        return self.answers.pop(0) if self.answers else []


def ctx(attempts: int) -> CommerceContext:
    import asyncio

    return CommerceContext(session_id=None, task_id=None, controller=None, policy=None, telemetry=None, binding=None,  # type: ignore[arg-type]
                           max_attempts=attempts, cancel_event=asyncio.Event())


async def test_empty_results_are_retried_a_bounded_number_of_times() -> None:
    adapter = FakeAdapter([[], [], [cand("Milk", "1 L")]])
    assert len(await search_with_retries(adapter, req("milk"), ctx(3))) == 1  # type: ignore[arg-type]
    assert adapter.calls == 3
    never = FakeAdapter([])
    assert await search_with_retries(never, req("milk"), ctx(2)) == []  # type: ignore[arg-type]
    assert never.calls == 2


async def test_cancel_stops_searching() -> None:
    c = ctx(3)
    c.cancel_event.set()
    adapter = FakeAdapter([[cand("Milk", "1 L")]])
    assert await search_with_retries(adapter, req("milk"), c) == [] and adapter.calls == 0  # type: ignore[arg-type]


def test_result_parser_keeps_unknowns_unknown() -> None:
    c = to_candidate({"name": "Amul Taaza Milk", "size": "1 ltr", "price": "₹56", "can_add": True, "ref": "k-3"}, CommercePlatform.BLINKIT, "page")
    assert c is not None and str(c.normalized_price) == "56.00" and c.dom_ref == "k-3"
    assert c.seller is None and c.rating is None and c.delivery_estimate is None and c.image_url is None
    bare = to_candidate({"name": "Mystery item"}, CommercePlatform.BLINKIT, "page")
    assert bare is not None and bare.availability == ProductAvailability.UNKNOWN and bare.normalized_price is None
    assert bare.extraction_confidence < c.extraction_confidence


def test_result_parser_rejects_unsafe_values() -> None:
    c = to_candidate({"name": "Phone", "url": "javascript:alert(1)", "image": "http://insecure/x.png", "ref": "#pay"},
                     CommercePlatform.AMAZON_IN, "page")
    assert c is not None and c.product_url is None and c.image_url is None and c.dom_ref is None
    assert to_candidate({"name": ""}, CommercePlatform.AMAZON_IN, "page") is None


def test_result_parser_redacts_and_bounds() -> None:
    rows = [{"name": f"Item {i} card 4111 1111 1111 1111"} for i in range(50)]
    out = to_candidates(rows, CommercePlatform.AMAZON_IN, "page", limit=10)
    assert len(out) == 10 and all("4111" not in c.product_name for c in out)
