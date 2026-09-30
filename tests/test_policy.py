import asyncio
import random
from dataclasses import replace

from keyword_reply.engine import compile_snapshot, evaluate
from keyword_reply.models import SendOutcome
from keyword_reply.policy import RuntimePolicy


async def reserve(policy, snapshot, message):
    return await policy.reserve(snapshot, message, evaluate(snapshot, message))


async def test_only_one_concurrent_group_reservation(snapshot, message, evaluation):
    policy = RuntimePolicy(lambda: 100)
    reservations = await asyncio.gather(
        *(policy.reserve(snapshot, message, evaluation) for _ in range(20))
    )
    assert sum(r is not None for r in reservations) == 1


async def test_success_cooldown_and_dedup_expire(snapshot, message):
    now = [100]
    policy = RuntimePolicy(lambda: now[0])
    first = await reserve(policy, snapshot, message)
    await policy.complete(first, (SendOutcome("echo", True, True),))
    assert await reserve(policy, snapshot, message) is None
    assert policy.last_reason(message) == "duplicate"
    repeated = replace(message, message_id="m2")
    assert await reserve(policy, snapshot, repeated) is None
    assert policy.last_reason(repeated) == "group_cooldown"
    now[0] += 3
    assert await reserve(policy, snapshot, repeated)


async def test_failed_send_has_dedup_but_no_cooldown(snapshot, message):
    policy = RuntimePolicy(lambda: 100)
    first = await reserve(policy, snapshot, message)
    await policy.complete(first, (SendOutcome("echo", True, False),))
    assert not policy._cooldowns
    assert await reserve(policy, snapshot, message) is None
    assert await reserve(policy, snapshot, replace(message, message_id="m2"))


async def test_unattempted_send_can_be_retried(snapshot, message):
    policy = RuntimePolicy(lambda: 100)
    first = await reserve(policy, snapshot, message)
    await policy.complete(first, ())
    assert await reserve(policy, snapshot, message)


async def test_only_first_enabled_match_replied(raw_rule, message):
    snapshot = compile_snapshot(
        {"rules": [dict(raw_rule, id="first"), dict(raw_rule, id="second")]}, "r"
    )
    policy = RuntimePolicy(lambda: 100)
    result = await reserve(policy, snapshot, message)
    assert [d.rule_id for d in result.deliveries] == ["first"]
    await policy.complete(result, ())
    policy.change_controls("off", "first")
    result = await reserve(policy, snapshot, message)
    assert [d.rule_id for d in result.deliveries] == ["second"]


async def test_random_reply_candidates_are_all_reachable(raw_rule, message):
    snapshot = compile_snapshot(
        {"group_cooldown_seconds": 0, "rules": [dict(raw_rule, replies=["a", "b"])]}, "r"
    )
    policy = RuntimePolicy(lambda: 100, random.Random(1))
    seen = set()
    for i in range(20):
        reservation = await reserve(policy, snapshot, replace(message, message_id=str(i)))
        seen.add(reservation.deliveries[0].text)
        await policy.complete(reservation, (SendOutcome("echo", True, True),))
    assert seen == {"a", "b"}


def test_preview_is_read_only(snapshot, message, evaluation):
    policy = RuntimePolicy(lambda: 100, random.Random(1))
    before = (policy.rng.getstate(), policy.export_persistent(), dict(policy.stats))
    assert policy.preview(snapshot, message, evaluation)
    assert (policy.rng.getstate(), policy.export_persistent(), dict(policy.stats)) == before


async def test_group_bot_platform_cooldown_isolation(snapshot, message):
    policy = RuntimePolicy(lambda: 100)
    first = await reserve(policy, snapshot, message)
    await policy.complete(first, (SendOutcome("echo", True, True),))
    for field in ["platform_id", "bot_id", "target_id"]:
        other = replace(message, scope=replace(message.scope, **{field: "other"}))
        assert await reserve(policy, snapshot, other)


async def test_disable_restored_and_applies_to_all_groups(snapshot, message):
    policy = RuntimePolicy(lambda: 100)
    policy.change_controls("off", "echo")
    clone = RuntimePolicy(lambda: 100)
    clone.restore_persistent(policy.export_persistent())
    other = replace(message, scope=replace(message.scope, target_id="other"))
    assert await reserve(clone, snapshot, other) is None
    clone.change_controls("on", "echo")
    assert await reserve(clone, snapshot, other)
