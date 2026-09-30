import math

import pytest

from keyword_reply.config import load_config
from keyword_reply.models import ConfigError


def test_defaults(raw_rule):
    loaded = load_config({"rules": [raw_rule]})
    assert loaded.settings.group_cooldown_seconds == 3
    assert loaded.rules[0].capture_mode == "any"


def test_duplicate_id_rejects_entire_snapshot(raw_rule):
    with pytest.raises(ConfigError):
        load_config({"rules": [raw_rule, dict(raw_rule)]})


@pytest.mark.parametrize("value", [-1, math.nan, math.inf, True, "1", 10**1000])
def test_invalid_cooldown_rejects_config(value):
    with pytest.raises(ConfigError):
        load_config({"group_cooldown_seconds": value})


@pytest.mark.parametrize(
    "changes",
    [
        {"id": ""},
        {"name": " "},
        {"enabled": "false"},
        {"replies": []},
        {"replies": [" "]},
        {"allowed_group_ids": [123]},
        {"typo": 1},
        {"match_type": "contains", "keywords": []},
        {"capture_mode": "all"},
    ],
)
def test_invalid_rule_isolated(raw_rule, changes):
    result = (
        load_config({"rules": [raw_rule, dict(raw_rule, id="bad", **changes)]})
        if "id" not in changes
        else load_config({"rules": [raw_rule, dict(raw_rule, **changes)]})
    )
    assert [r.id for r in result.rules] == ["echo"]
    assert result.issues


@pytest.mark.parametrize("raw", [{"enabled": "false"}, {"rules": [{}] * 501}, {"unknown": 0}, []])
def test_invalid_global_config_rejected(raw):
    with pytest.raises(ConfigError):
        load_config(raw)


def test_metadata_allowed_and_disabled_rule_validated(raw_rule):
    valid = dict(raw_rule, enabled=False, __template_key="template")
    assert len(load_config({"rules": [valid]}).rules) == 1
    assert load_config({"rules": [dict(valid, replies=[])]}).issues
