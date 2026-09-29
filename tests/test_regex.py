import pytest

from keyword_reply.config import load_config
from keyword_reply.matching import compile_matcher


def test_named_numbered_optional_groups(raw_rule):
    raw_rule.update(match_type="regex", pattern=r"我(?P<动作>吃)(饭)?什么")
    compiled = compile_matcher(load_config({"rules": [raw_rule]}).rules[0])
    result = compiled.search("我吃什么", timeout_s=0.01)
    assert result.groups == {"1": "吃", "2": "", "动作": "吃"}
    assert compiled.capture_names == frozenset({"1", "2", "动作"})


def test_pathological_expression_has_actual_timeout(raw_rule):
    raw_rule.update(match_type="regex", pattern=r"(a|aa)+$")
    compiled = compile_matcher(load_config({"rules": [raw_rule]}).rules[0])
    with pytest.raises(TimeoutError):
        compiled.search("a" * 2000 + "!", timeout_s=0.001)


def test_invalid_regex_fails_at_compile(raw_rule):
    raw_rule.update(match_type="regex", pattern="[")
    with pytest.raises(ValueError):
        compile_matcher(load_config({"rules": [raw_rule]}).rules[0])
