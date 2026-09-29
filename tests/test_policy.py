import asyncio
import random
from dataclasses import replace

import pytest

from keyword_reply.engine import compile_snapshot, evaluate
from keyword_reply.models import SendOutcome
from keyword_reply.policy import RuntimePolicy


class Clock:
    now = 100.0

    def __call__(self):
        return self.now


def make(raw_rule, **settings):
    return compile_snapshot({"rules": [raw_rule], **settings}, "r1")


async def reserve(policy, snapshot, message):
    return await policy.reserve(snapshot, message, evaluate(snapshot, message, clock=lambda: 0))


async def test_only_one_concurrent_group_reservation(snapshot, message, evaluation):
    policy = RuntimePolicy(clock=lambda: 100, rng=random.Random(7))
    a, b = await asyncio.gather(
        policy.reserve(snapshot, message, evaluation),
        policy.reserve(snapshot, replace(message, message_id="m2"), evaluation),
    )
    assert sum(x is not None for x in (a, b)) == 1


async def test_cooldown_dedup_and_real_repeated_text(raw_rule, message):
    clock = Clock()
    p = RuntimePolicy(clock, random.Random(1))
    s = make(raw_rule)
    first = await reserve(p, s, message)
    await p.complete(first, (SendOutcome("echo", True, True, None),))
    assert await reserve(p, s, replace(message, message_id="m2")) is None
    clock.now += 4
    assert await reserve(p, s, replace(message, message_id="m2")) is None
    assert p.last_reason(replace(message, message_id="m2")) == "user_cooldown"
    clock.now += 7
    assert await reserve(p, s, message) is None
    assert p.last_reason(message) == "duplicate"
    assert await reserve(p, s, replace(message, message_id="m2")) is not None


async def test_failure_releases_busy_without_advancing_cursor(raw_rule, message):
    p = RuntimePolicy(lambda: 100, random.Random(1))
    s = make(dict(raw_rule, reply_mode="round_robin", replies=["a", "b"]))
    before = p.export_persistent()
    first = await reserve(p, s, message)
    await p.complete(first, (SendOutcome("echo", True, False, "send_failed"),))
    assert p.export_persistent() == before
    assert await reserve(p, s, message) is None
    second = await reserve(p, s, replace(message, message_id="m2"))
    assert second.deliveries[0].text == "a"


async def test_unattempted_releases_dedup(snapshot, message):
    p = RuntimePolicy(lambda: 100, random.Random(1))
    first = await reserve(p, snapshot, message)
    await p.complete(first, ())
    assert await reserve(p, snapshot, message) is not None


async def test_priority_probability_and_rule_cooldown_fallback(raw_rule, message):
    rules = [dict(raw_rule, id="high", priority=5, probability=0), dict(raw_rule, id="low")]
    s = compile_snapshot({"rules": rules, "group_cooldown_seconds": 0}, "r")
    p = RuntimePolicy(lambda: 100, random.Random(1))
    first = await reserve(p, s, message)
    assert first.deliveries[0].rule_id == "low"
    await p.complete(first, (SendOutcome("low", True, True, None),))
    rules[0]["probability"] = 1
    s = compile_snapshot({"rules": rules, "group_cooldown_seconds": 0}, "r2")
    assert (await reserve(p, s, replace(message, message_id="m2"))).deliveries[0].rule_id == "high"


@pytest.mark.parametrize("mode", ["priority", "random", "all"])
async def test_selection_modes_and_limit(raw_rule, message, mode):
    rules = [dict(raw_rule, id=str(i), priority=i) for i in range(5)]
    s = compile_snapshot({"rules": rules, "selection_mode": mode}, "r")
    p = RuntimePolicy(lambda: 100, random.Random(1))
    result = await reserve(p, s, message)
    ids = [d.rule_id for d in result.deliveries]
    if mode == "priority":
        assert ids == ["4"]
    elif mode == "all":
        assert ids == ["4", "3", "2"]
    else:
        assert len(ids) == 1 and ids[0] in {"0", "1", "2", "3", "4"}


async def test_round_robin_commit(raw_rule, message):
    rule = dict(
        raw_rule, replies=["a", "b"], reply_mode="round_robin", user_rule_cooldown_seconds=0
    )
    s = make(rule, group_cooldown_seconds=0)
    p = RuntimePolicy(lambda: 100, random.Random(1))
    for i, text in enumerate(["a", "b", "a"]):
        current = await reserve(p, s, replace(message, message_id=str(i)))
        assert current.deliveries[0].text == text
        await p.complete(current, (SendOutcome("echo", True, True, None),))


def test_preview_is_read_only(snapshot, message, evaluation):
    p = RuntimePolicy(lambda: 100, random.Random(1))
    before = (p.rng.getstate(), p.export_persistent(), dict(p.stats))
    assert p.preview(snapshot, message, evaluation)
    assert (p.rng.getstate(), p.export_persistent(), dict(p.stats)) == before


async def test_scope_isolation(snapshot, message):
    p = RuntimePolicy(lambda: 100, random.Random(1))
    assert await reserve(p, snapshot, message)
    for field in ("platform_id", "bot_id", "target_id"):
        assert await reserve(
            p, snapshot, replace(message, scope=replace(message.scope, **{field: "different"}))
        )


async def test_runtime_disable_and_restore(snapshot, message):
    p = RuntimePolicy(lambda: 100, random.Random(1))
    p.change_controls("off", "echo", message.scope, False)
    assert await reserve(p, snapshot, message) is None
    clone = RuntimePolicy(lambda: 100, random.Random(1))
    clone.restore_persistent(p.export_persistent())
    assert await reserve(clone, snapshot, message) is None
    clone.change_controls("on", "echo", message.scope, False)
    assert await reserve(clone, snapshot, message)
