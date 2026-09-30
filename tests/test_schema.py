import json
from dataclasses import asdict
from pathlib import Path

from keyword_reply.engine import compile_snapshot
from keyword_reply.models import PluginConfig


def schema():
    return json.loads(Path("_conf_schema.json").read_text(encoding="utf-8"))


def test_form_defaults_compile_and_each_template_can_reply():
    raw = {k: v["default"] for k, v in schema().items()}
    assert asdict(compile_snapshot(raw, "schema").settings) == asdict(PluginConfig())
    for key, template in schema()["rules"]["templates"].items():
        example = {k: v["default"] for k, v in template["items"].items()}
        example.update(id="sample", name="示例", replies=["回复"], __template_key=key)
        if key == "keyword":
            example["keywords"] = ["晚安"]
        result = compile_snapshot({"rules": [example]}, key)
        assert result.issues == ()


def test_examples_valid_and_disabled():
    raw = json.loads(Path("examples/rules.json").read_text(encoding="utf-8"))
    compiled = compile_snapshot(raw, "examples")
    assert compiled.issues == ()
    assert len(compiled.rules) == 2
    assert all(not item.rule.enabled for item in compiled.rules)
