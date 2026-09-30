import json
from pathlib import Path


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
        elif key == "regex":
            entry["pattern"] = "^晚安$"
        assert compile_snapshot({"rules": [entry]}, key).issues == ()
