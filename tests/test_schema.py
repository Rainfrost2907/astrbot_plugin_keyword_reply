import json
from dataclasses import asdict, fields
from pathlib import Path

from keyword_reply.engine import compile_snapshot
from keyword_reply.models import PluginConfig, Rule


def schema():
    return json.loads(Path("_conf_schema.json").read_text(encoding="utf-8"))


def test_defaults_and_all_template_fields():
    raw = {k: v["default"] for k, v in schema().items()}
    compiled = compile_snapshot(raw, "schema")
    assert asdict(compiled.settings) == asdict(PluginConfig())
    for key, template in schema()["rules"]["templates"].items():
        assert set(template["items"]) == {f.name for f in fields(Rule)} - {"order"}
        example = {k: v["default"] for k, v in template["items"].items()}
        example.update(id="sample", name="示例", replies=["是啊{关键词}什么"], __template_key=key)
        if key == "keyword":
            example["keywords"] = ["晚安"]
        elif key == "regex":
            example["pattern"] = "^我(.+?)什么$"
        result = compile_snapshot({"rules": [example]}, key)
        assert result.issues == ()


def test_all_examples_valid_and_disabled():
    raw = json.loads(Path("examples/rules.json").read_text(encoding="utf-8"))
    compiled = compile_snapshot(raw, "examples")
    assert compiled.issues == ()
    assert len(compiled.rules) == 4
    assert all(not c.rule.enabled for c in compiled.rules)
