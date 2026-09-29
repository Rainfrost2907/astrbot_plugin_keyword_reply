import pytest


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
