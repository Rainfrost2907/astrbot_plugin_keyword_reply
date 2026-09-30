import pytest

from keyword_reply.config import load_config
from keyword_reply.matching import compile_matcher


def match(raw, text):
    return compile_matcher(load_config({"rules": [raw]}).rules[0]).search(text, timeout_s=0.01)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("我吃什么", "吃"),
        (" 我学习什么 ", "学习"),
        ("我😀什么", "😀"),
        ("我什么", None),
        ("我   什么", None),
        ("今天我吃什么", None),
        ("我吃什么？", None),
        ("我吃\n饭什么", None),
        ("我" + "x" * 129 + "什么", None),
    ],
)
def test_sentence_full_match(raw_rule, text, expected):
    found = match(raw_rule, text)
    assert (found.keyword if found else None) == expected


def test_sentence_limited_to_literal_word_list(raw_rule):
    rule = dict(raw_rule, capture_mode="keywords", keywords=["吃", "吃饭", "a+b"])
    assert match(rule, "我吃饭什么").keyword == "吃饭"
    assert match(rule, "我a+b什么").keyword == "a+b"
    assert match(rule, "我学习什么") is None


@pytest.mark.parametrize(
    "text,expected", [("要吃饭", "吃饭"), ("喝水吃饭", "喝"), ("不睡觉", None)]
)
def test_keyword_earliest_longest_match(raw_rule, text, expected):
    found = match(dict(raw_rule, match_type="contains", keywords=["吃", "吃饭", "喝"]), text)
    assert (found.keyword if found else None) == expected


def test_punctuation_and_braces_are_literal(raw_rule):
    assert match(dict(raw_rule, pattern="(我){关键词}."), "(我)吃.").keyword == "吃"
    assert match(dict(raw_rule, pattern="{{我}}{关键词}."), "{我}吃.").keyword == "吃"
    assert match(dict(raw_rule, pattern="I{关键词}?"), "iabc?") is None


@pytest.mark.parametrize(
    "pattern", ["我什么", "{关键词}{关键词}", "我{其他}", "我{关键词", "我}什么"]
)
def test_bad_template_rejected(raw_rule, pattern):
    with pytest.raises(ValueError):
        compile_matcher(load_config({"rules": [dict(raw_rule, pattern=pattern)]}).rules[0])
