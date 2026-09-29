import pytest

from keyword_reply.config import load_config
from keyword_reply.matching import compile_matcher


def match(raw, text):
    rule = load_config({"rules": [raw]}).rules[0]
    return compile_matcher(rule).search(text, timeout_s=0.01)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("我吃什么", "吃"),
        ("我学习什么", "学习"),
        ("我😀什么", "😀"),
        ("我什么", None),
        ("我   什么", None),
        ("今天我吃什么", None),
        ("我吃什么？", None),
        ("我吃\n饭什么", None),
    ],
)
def test_template_full_match(raw_rule, text, expected):
    found = match(raw_rule, text)
    assert (found.keyword if found else None) == expected


def test_template_limits_and_options(raw_rule):
    assert match(dict(raw_rule, capture_max=1), "我吃饭什么") is None
    assert (
        match(dict(raw_rule, ignore_trailing_question_marks=True), " 我吃什么？？ ").keyword == "吃"
    )
    assert match(dict(raw_rule, match_scope="search"), "今天我吃什么？").keyword == "吃"
    assert (
        match(dict(raw_rule, capture_mode="keywords", keywords=["吃", "喝"]), "我学习什么") is None
    )
    assert (
        match(
            dict(raw_rule, capture_mode="keywords", keywords=["吃", "吃饭"]), "我吃饭什么"
        ).keyword
        == "吃饭"
    )


@pytest.mark.parametrize(
    ("mode", "text", "expected"),
    [
        ("exact", "吃饭", "吃饭"),
        ("exact", "要吃饭", None),
        ("contains", "要吃饭", "吃饭"),
        ("prefix", "吃饭啦", "吃饭"),
        ("prefix", "要吃饭", None),
        ("suffix", "要吃饭", "吃饭"),
        ("suffix", "吃饭啦", None),
    ],
)
def test_literals(raw_rule, mode, text, expected):
    result = match(dict(raw_rule, match_type=mode, keywords=["吃", "吃饭"]), text)
    assert (result.keyword if result else None) == expected


def test_case_preserves_original_capture_and_literal_syntax(raw_rule):
    assert match(dict(raw_rule, pattern="I{关键词}?", ignore_case=True), "iAbC?").keyword == "AbC"
    assert match(dict(raw_rule, pattern="(我){关键词}."), "(我)吃.").keyword == "吃"
    assert match(dict(raw_rule, pattern="{{我}}{关键词}."), "{我}吃.").keyword == "吃"
    literal = dict(raw_rule, match_type="contains", keywords=["ab", "ABC"], ignore_case=True)
    assert match(literal, "xAbC").keyword == "AbC"


@pytest.mark.parametrize(
    "pattern", ["我什么", "{关键词}{关键词}", "我{其他}", "我{关键词", "我}什么"]
)
def test_bad_template_rejected(raw_rule, pattern):
    with pytest.raises(ValueError):
        compile_matcher(load_config({"rules": [dict(raw_rule, pattern=pattern)]}).rules[0])
