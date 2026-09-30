"""Public behavior of the intentionally smaller v2 configuration."""

import json
from pathlib import Path

import pytest

from keyword_reply.commands import parse_command
from keyword_reply.config import load_config
from keyword_reply.models import ConfigError


@pytest.mark.parametrize(
    "key,value", [("selection_mode", "all"), ("allow_private", True), ("platform_ids", ["p1"])]
)
def test_removed_global_options_are_reported(key, value):
    with pytest.raises(ConfigError):
        load_config({key: value})


@pytest.mark.parametrize(
    "extra",
    [
        {"match_type": "regex", "pattern": "^x$"},
        {"priority": 1},
        {"probability": 0.5},
        {"reply_mode": "round_robin"},
        {"allowed_user_ids": ["2000"]},
    ],
)
def test_removed_rule_options_do_not_silently_broaden_matching(raw_rule, extra):
    result = load_config({"rules": [dict(raw_rule, **extra)]})
    assert not result.rules
    assert result.issues


@pytest.mark.parametrize(
    "body", ["kwr off echo here", "kwr off echo global", "kwr reset", "kwr stats"]
)
def test_commands_reject_removed_scope_and_advanced_operations(body):
    with pytest.raises(ValueError):
        parse_command(body)


def test_form_only_offers_basic_reply_workflows():
    form = json.loads(Path("_conf_schema.json").read_text(encoding="utf-8"))
    assert {key for key, node in form.items() if not node.get("invisible")} == {
        "enabled",
        "group_cooldown_seconds",
        "rules",
    }
    assert set(form["rules"]["templates"]) == {"keyword", "template"}
    keyword = form["rules"]["templates"]["keyword"]["items"]
    visible = {k for k, v in keyword.items() if not v.get("invisible") and not v.get("condition")}
    assert visible == {
        "id",
        "name",
        "enabled",
        "keywords",
        "replies",
        "allowed_group_ids",
        "require_at",
    }
