from dataclasses import replace

import pytest

from keyword_reply.config import load_config
from keyword_reply.models import Match
from keyword_reply.rendering import compile_replies, render_all


def test_capture_not_evaluated_again(raw_rule, message):
    rule = load_config({"rules": [raw_rule]}).rules[0]
    result = render_all(
        compile_replies(rule, frozenset()), Match("{用户ID}", "x", {}), message, max_chars=2000
    )
    assert result == ("是啊{用户ID}什么",)


def test_all_context_and_escaping(raw_rule, message):
    raw_rule["replies"] = [
        "{{{关键词}}}:{匹配文本}:{消息}:{用户ID}:{用户名}:{群ID}:{规则ID}:{规则名}"
    ]
    rule = load_config({"rules": [raw_rule]}).rules[0]
    result = render_all(
        compile_replies(rule, frozenset()), Match("吃", "我吃什么", {}), message, max_chars=2000
    )
    assert result == ("{吃}:我吃什么:我吃什么:2000:小明:1000:echo:句式回复",)


@pytest.mark.parametrize(
    "text", ["{其他}", "{用户ID.__class__}", "{用户ID[0]}", "{关键词", "a}", "{捕获.未知}"]
)
def test_invalid_placeholder_rejected(raw_rule, text):
    rule = load_config({"rules": [dict(raw_rule, replies=[text])]}).rules[0]
    with pytest.raises(ValueError):
        compile_replies(rule, frozenset())


def test_optional_groups_and_empty_overlong_candidates(raw_rule, message):
    raw_rule["replies"] = ["{捕获.1}", "ok", "{消息}{消息}"]
    rule = load_config({"rules": [raw_rule]}).rules[0]
    result = render_all(
        compile_replies(rule, frozenset({"1"})), Match("", "", {"1": ""}), message, max_chars=5
    )
    assert result == ("ok",)


def test_missing_name_and_private_group(raw_rule, message):
    rule = load_config({"rules": [dict(raw_rule, replies=["{用户名}/{群ID}"])]}).rules[0]
    ctx = replace(
        message, user_name="", scope=replace(message.scope, chat_type="private", target_id="2000")
    )
    assert render_all(compile_replies(rule, frozenset()), Match("", "", {}), ctx, max_chars=20) == (
        "2000/",
    )
