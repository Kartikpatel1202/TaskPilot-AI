"""Session memory: storage, isolation, context, follow-ups, limits, expiry and redaction."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.agent.memory import MemoryManager
from app.agent.memory.summarizer import MAX_SUMMARY_CHARS
from app.schemas.intent import IntentClassification, IntentEntities, IntentType, ProductEntity
from app.schemas.memory import ConversationRole


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


def manager(clock: Clock | None = None, **kw: int) -> MemoryManager:
    defaults = {"max_turns": 20, "max_characters": 12_000, "ttl_minutes": 60, "max_sessions": 1000}
    defaults.update(kw)
    return MemoryManager(clock=clock or Clock(), **defaults)


def shopping(products: list[ProductEntity], follow_up: bool = False, site: str = "blinkit.com") -> IntentClassification:
    return IntentClassification(intent=IntentType.ECOMMERCE_SHOPPING, confidence=0.9, target_website=site,
                                entities=IntentEntities(products=products), is_follow_up=follow_up)


def test_turns_are_stored_in_order() -> None:
    mem, sid, tid = manager(), uuid4(), uuid4()
    mem.add_user_turn(sid, tid, "Blinkit par 2 litre Amul milk add karo")
    mem.add_assistant_turn(sid, tid, "Haan bhai, plan bana raha hoon", IntentType.ECOMMERCE_SHOPPING)
    turns = mem.turns(sid)
    assert [t.role for t in turns] == [ConversationRole.USER, ConversationRole.ASSISTANT]
    assert turns[1].intent == IntentType.ECOMMERCE_SHOPPING and turns[0].task_id == tid


def test_sessions_are_isolated() -> None:
    mem, a, b = manager(), uuid4(), uuid4()
    mem.add_user_turn(a, None, "Remember that I want to shop on Blinkit")
    mem.remember_classification(a, uuid4(), shopping([ProductEntity(name="milk")]))
    mem.add_user_turn(b, None, "Find a laptop on Amazon")
    assert all("Blinkit" not in t.content for t in mem.turns(b))
    assert mem.build_context(b).session_context.active_website is None
    assert mem.build_context(a).session_context.active_website == "blinkit.com"


def test_context_retrieval_and_follow_up_context() -> None:
    mem, sid, t1 = manager(), uuid4(), uuid4()
    mem.add_user_turn(sid, t1, "Open Blinkit and prepare my grocery cart with 2L Amul milk.")
    mem.remember_classification(sid, t1, shopping([ProductEntity(name="milk", brand="Amul", quantity=2, unit="litre")]))
    ctx = mem.build_context(sid)
    assert ctx.session_context.active_intent == IntentType.ECOMMERCE_SHOPPING
    assert ctx.session_context.products[0].brand == "Amul"
    assert ctx.recent_turns[0].content.startswith("Open Blinkit")
    # A follow-up classification replaces the product list with the merged set.
    mem.remember_classification(sid, uuid4(), shopping([ProductEntity(name="milk"), ProductEntity(name="bread")], follow_up=True))
    assert [p.name for p in mem.build_context(sid).session_context.products] == ["milk", "bread"]


def test_switching_store_resets_basket() -> None:
    mem, sid = manager(), uuid4()
    mem.remember_classification(sid, uuid4(), shopping([ProductEntity(name="milk")]))
    mem.remember_classification(sid, uuid4(), shopping([], site="amazon.in"))
    ctx = mem.build_context(sid).session_context
    assert ctx.active_website == "amazon.in" and ctx.products == []


def test_context_prioritises_current_task_within_budget() -> None:
    mem, sid, current = manager(), uuid4(), uuid4()
    for i in range(10):
        mem.add_user_turn(sid, uuid4(), f"old message {i} " + "x" * 50)
    mem.add_user_turn(sid, current, "current task message")
    ctx = mem.build_context(sid, current, budget=200)
    contents = [t.content for t in ctx.recent_turns]
    assert "current task message" in contents
    assert sum(len(c) for c in contents) <= 200


def test_max_turn_limit_summarises_evicted_turns() -> None:
    mem, sid = manager(max_turns=4), uuid4()
    for i in range(10):
        mem.add_user_turn(sid, None, f"message number {i}")
    assert len(mem.turns(sid)) == 4
    summary = mem.build_context(sid).summary or ""
    assert "message number 0" in summary and len(summary) <= MAX_SUMMARY_CHARS


def test_character_limit_is_enforced() -> None:
    mem, sid = manager(max_characters=1000), uuid4()
    for _ in range(10):
        mem.add_user_turn(sid, None, "y" * 300)
    total = sum(len(t.content) for t in mem.turns(sid))
    assert total <= 1000
    huge = mem.add_user_turn(uuid4(), None, "z" * 5000)
    assert len(huge.content) <= 1000


def test_ttl_expiry_and_session_expiration() -> None:
    clock = Clock()
    mem, sid = manager(clock, ttl_minutes=60), uuid4()
    mem.add_user_turn(sid, None, "hello")
    clock.now += timedelta(minutes=30)
    assert mem.has_session(sid)  # access refreshes the TTL
    clock.now += timedelta(minutes=61)
    assert mem.turns(sid) == []
    mem.add_user_turn(uuid4(), None, "a")
    clock.now += timedelta(hours=2)
    assert mem.prune_expired() == 1 and mem.session_count == 0


def test_max_sessions_is_bounded() -> None:
    mem = manager(max_sessions=3)
    ids = [uuid4() for _ in range(5)]
    for sid in ids:
        mem.add_user_turn(sid, None, "hi")
    assert mem.session_count == 3
    assert mem.turns(ids[0]) == [] and mem.turns(ids[-1])


def test_sensitive_values_are_redacted_before_storage() -> None:
    mem, sid = manager(), uuid4()
    mem.add_user_turn(sid, None, "Pay with card 4111 1111 1111 1111, OTP is 482913 and password: hunter2")
    stored = mem.turns(sid)[0].content
    for secret in ("4111 1111 1111 1111", "482913", "hunter2"):
        assert secret not in stored


def test_no_cross_session_access_path() -> None:
    mem = manager()
    a, b = uuid4(), uuid4()
    mem.add_user_turn(a, None, "secret plan A")
    # The only read APIs are keyed by session id; another id sees nothing.
    assert mem.turns(b) == [] and mem.build_context(b).recent_turns == []
