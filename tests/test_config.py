import math

import pytest

from keyword_reply.config import load_config
from keyword_reply.models import ConfigError


def test_defaults(raw_rule):
    loaded = load_config({"rules": [raw_rule]})
    assert loaded.settings.group_cooldown_seconds == 3.0
    assert loaded.rules[0].user_rule_cooldown_seconds == 10.0
    assert loaded.rules[0].match_scope == "full"


def test_duplicate_id_rejects_entire_snapshot(raw_rule):
    with pytest.raises(ConfigError):
        load_config({"rules": [raw_rule, dict(raw_rule)]})


@pytest.mark.parametrize("value", [2, -1, math.nan, math.inf, True, "1"])
def test_bad_probability_isolates_rule(raw_rule, value):
    bad = dict(raw_rule, id="bad", probability=value)
    result = load_config({"rules": [raw_rule, bad]})
    assert [r.id for r in result.rules] == ["echo"]
    assert result.issues[0].path == "rules[1].probability"


@pytest.mark.parametrize(
    "changes",
    [
        {"id": ""},
        {"name": " "},
        {"priority": True},
        {"enabled": "false"},
        {"replies": []},
        {"replies": [" "]},
        {"allowed_group_ids": [123.4]},
        {"chat_types": "all"},
        {"capture_min": 10, "capture_max": 2},
        {"typo": 1},
        {"match_type": "contains", "keywords": []},
    ],
)
def test_invalid_fields_are_reported(raw_rule, changes):
    result = load_config({"rules": [dict(raw_rule, **changes)]})
    assert not result.rules
    assert result.issues


@pytest.mark.parametrize(
    "raw",
    [
        {"enabled": "false"},
        {"max_replies": 0},
        {"max_input_chars": True},
        {"rules": [{}] * 501},
        {"unknown": 0},
        [],
    ],
)
def test_invalid_global_config_rejected(raw):
    with pytest.raises(ConfigError):
        load_config(raw)


def test_metadata_allowed_and_disabled_rule_validated(raw_rule):
    valid = dict(raw_rule, enabled=False, __template_key="template")
    assert len(load_config({"rules": [valid]}).rules) == 1
    assert load_config({"rules": [dict(valid, replies=[])]}).issues
