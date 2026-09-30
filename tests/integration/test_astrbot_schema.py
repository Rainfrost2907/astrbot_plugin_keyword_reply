import json
from pathlib import Path

import pytest


def test_native_framework_builds_defaults():
    from astrbot.core.config import AstrBotConfig

    from keyword_reply.engine import compile_snapshot

    schema = json.loads(Path("_conf_schema.json").read_text(encoding="utf-8"))
    parser = AstrBotConfig.__new__(AstrBotConfig)
    defaults = parser._config_schema_to_default_config(schema)
    assert compile_snapshot(defaults, "native").issues == ()
    for key, template in schema["rules"]["templates"].items():
        entry = parser._config_schema_to_default_config(template["items"])
        entry.update(id="native", name="原生", replies=["回复"], __template_key=key)
        if key == "keyword":
            entry["keywords"] = ["晚安"]
        assert compile_snapshot({"rules": [entry]}, key).issues == ()


@pytest.mark.parametrize(
    "key,value",
    [
        ("platform_ids", ["old-platform"]),
        ("blocked_user_ids", ["2000"]),
        ("allow_private", False),
        ("selection_mode", "priority"),
        ("max_replies", 3),
        ("dedup_ttl_seconds", 120),
        ("max_input_chars", 4096),
        ("max_reply_chars", 2000),
        ("regex_timeout_ms", 10),
        ("evaluation_budget_ms", 100),
        ("max_rules", 500),
        ("ignore_command_prefixes", ["/"]),
    ],
)
def test_native_normalization_cannot_erase_old_global_constraints(tmp_path, raw_rule, key, value):
    from astrbot.core.config import AstrBotConfig

    from keyword_reply.engine import compile_snapshot
    from keyword_reply.models import ConfigError

    schema = json.loads(Path("_conf_schema.json").read_text(encoding="utf-8"))
    path = tmp_path / "plugin_config.json"
    path.write_text(json.dumps({"rules": [raw_rule], key: value}), encoding="utf-8")
    native = AstrBotConfig(config_path=str(path), schema=schema)
    with pytest.raises(ConfigError) as exc:
        compile_snapshot(dict(native), "old-config")
    assert any(issue.path == key for issue in exc.value.issues)


def test_native_dashboard_save_keeps_new_config_valid():
    from astrbot.core.config import AstrBotConfig
    from astrbot.dashboard.services.config_service import validate_config

    from keyword_reply.engine import compile_snapshot

    schema = json.loads(Path("_conf_schema.json").read_text(encoding="utf-8"))
    parser = AstrBotConfig.__new__(AstrBotConfig)
    defaults = parser._config_schema_to_default_config(schema)
    entry = parser._config_schema_to_default_config(
        schema["rules"]["templates"]["keyword"]["items"]
    )
    entry.update(
        id="night",
        name="晚安",
        keywords=["晚安"],
        replies=["晚安"],
        enabled=True,
        __template_key="keyword",
    )
    defaults["rules"] = [entry]
    errors, saved = validate_config(defaults, schema, is_core=False)
    assert errors == []
    assert compile_snapshot(saved, "dashboard-save").issues == ()
