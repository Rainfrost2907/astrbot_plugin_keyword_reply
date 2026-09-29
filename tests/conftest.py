import pytest

from keyword_reply.models import MessageContext, ScopeKey


@pytest.fixture
def raw_rule():
    return {
        "id": "echo",
        "name": "句式回复",
        "match_type": "template",
        "pattern": "我{关键词}什么",
        "capture_mode": "any",
        "replies": ["是啊{关键词}什么"],
    }


@pytest.fixture
def message():
    return MessageContext(ScopeKey("p1", "9000", "group", "1000"), "2000", "小明", "m1", "我吃什么")
