from dataclasses import replace

import pytest

from keyword_reply.engine import compile_snapshot, evaluate
from keyword_reply.models import ConfigError


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"enabled": False}, "disabled"),
        ({"require_at": True}, "needs_at"),
        ({"allowed_group_ids": ["other"]}, "scope_denied"),
        ({"pattern": "别{关键词}什么"}, "no_match"),
    ],
)
def test_rule_filters(raw_rule, message, changes, reason):
    result = evaluate(compile_snapshot({"rules": [dict(raw_rule, **changes)]}, "r"), message)
    assert not result.candidates
    assert result.traces[0].reason == reason


def test_list_order_and_invalid_rule_isolation(raw_rule, message):
    rules = [
        dict(raw_rule, id="a"),
        dict(raw_rule, id="b"),
        dict(raw_rule, id="bad", pattern="oops"),
    ]
    snapshot = compile_snapshot({"rules": rules}, "r")
    result = evaluate(snapshot, message)
    assert [c.rule.id for c in result.candidates] == ["a", "b"]
    assert result.candidates[0].replies == ("是啊吃什么",)
    assert snapshot.issues[0].rule_id == "bad"


def test_total_budget_discards_partial_results(raw_rule, message):
    snapshot = compile_snapshot({"rules": [raw_rule, dict(raw_rule, id="b")]}, "r")
    ticks = iter([0, 0, 1, 1, 1])
    result = evaluate(snapshot, message, clock=lambda: next(ticks))
    assert result.exhausted and not result.candidates


def test_private_never_automatically_replied(snapshot, message):
    private = replace(message, scope=replace(message.scope, chat_type="private"))
    result = evaluate(snapshot, private)
    assert not result.candidates and result.traces[0].reason == "wrong_chat_type"


def test_global_failure_and_reply_validation(raw_rule):
    with pytest.raises(ConfigError):
        compile_snapshot({"enabled": "invalid"}, "r")
    snapshot = compile_snapshot({"rules": [dict(raw_rule, replies=["{不存在}"])]}, "r")
    assert not snapshot.rules and snapshot.issues[0].path.endswith("replies")


def test_overlong_input_not_truncated(snapshot, message):
    result = evaluate(snapshot, replace(message, text="我" + "吃" * 4096 + "什么"))
    assert not result.candidates and result.traces[0].reason == "input_too_long"
