from dataclasses import replace

import pytest

from keyword_reply.engine import compile_snapshot, evaluate
from keyword_reply.models import ConfigError


def test_blacklist_wins(raw_rule, message):
    raw_rule.update(allowed_user_ids=["2000"], blocked_user_ids=["2000"])
    ev = evaluate(compile_snapshot({"rules": [raw_rule]}, "r1"), message, clock=lambda: 0)
    assert not ev.candidates
    assert ev.traces[0].reason == "scope_denied"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"enabled": False}, "disabled"),
        ({"require_at": True}, "needs_at"),
        ({"allowed_group_ids": ["other"]}, "scope_denied"),
        ({"platform_ids": ["other"]}, "wrong_platform"),
        ({"chat_types": "private"}, "wrong_chat_type"),
        ({"exclude_keywords": ["吃"]}, "excluded"),
        ({"pattern": "别{关键词}什么"}, "no_match"),
    ],
)
def test_rule_filters(raw_rule, message, changes, reason):
    ev = evaluate(
        compile_snapshot({"rules": [dict(raw_rule, **changes)]}, "r1"), message, clock=lambda: 0
    )
    assert not ev.candidates
    assert ev.traces[0].reason == reason


def test_sorting_and_invalid_rule_isolation(raw_rule, message):
    rules = [
        dict(raw_rule, id="a"),
        dict(raw_rule, id="b", priority=5),
        dict(raw_rule, id="c", priority=5),
        dict(raw_rule, id="bad", pattern="oops"),
    ]
    snapshot = compile_snapshot({"rules": rules}, "r1")
    ev = evaluate(snapshot, message, clock=lambda: 0)
    assert [x.rule.id for x in ev.candidates] == ["b", "c", "a"]
    assert ev.candidates[0].replies == ("是啊吃什么",)
    assert snapshot.issues[0].rule_id == "bad"


def test_total_budget_discards_partial_results(raw_rule, message):
    snapshot = compile_snapshot({"rules": [raw_rule, dict(raw_rule, id="b")]}, "r1")
    ticks = iter([0, 0, 1, 1, 1, 1])
    ev = evaluate(snapshot, message, clock=lambda: next(ticks))
    assert ev.exhausted and not ev.candidates


def test_regex_timeout_is_diagnostic(raw_rule, message):
    raw_rule.update(match_type="regex", pattern="(a|aa)+$")
    snapshot = compile_snapshot({"regex_timeout_ms": 1, "rules": [raw_rule]}, "r1")
    ev = evaluate(
        snapshot, replace(message, text="a" * 2000 + "!"), clock=__import__("time").monotonic
    )
    assert not ev.candidates
    assert ev.traces[0].reason == "regex_timeout"


def test_private_global_and_rule_gate(raw_rule, message):
    private = replace(message, scope=replace(message.scope, chat_type="private"))
    raw_rule.update(chat_types="both", require_at=True)
    assert not evaluate(
        compile_snapshot({"rules": [raw_rule]}, "r"), private, clock=lambda: 0
    ).candidates
    assert evaluate(
        compile_snapshot({"allow_private": True, "rules": [raw_rule]}, "r"),
        private,
        clock=lambda: 0,
    ).candidates


def test_global_failure_and_reply_validation(raw_rule):
    with pytest.raises(ConfigError):
        compile_snapshot({"selection_mode": "invalid"}, "r")
    s = compile_snapshot({"rules": [dict(raw_rule, replies=["{不存在}"])]}, "r")
    assert not s.rules and s.issues[0].path.endswith("replies")


def test_overlong_input_not_truncated(raw_rule, message):
    s = compile_snapshot({"max_input_chars": 128, "rules": [raw_rule]}, "r")
    assert not evaluate(
        s, replace(message, text="我" + "吃" * 200 + "什么"), clock=lambda: 0
    ).candidates
