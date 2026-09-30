from dataclasses import replace

from keyword_reply.astrbot_adapter import extract_message


def test_raw_plain_preserves_prefix_and_excludes_quote(onebot_event):
    from astrbot.api.message_components import Plain, Reply

    onebot_event.message_str = "我吃什么"
    onebot_event.message_obj.message = [
        Reply(id="q", message_str="quoted"),
        Plain("/我"),
        Plain("吃什么"),
    ]
    message = extract_message(onebot_event)
    assert message.text == "/我吃什么"
    assert message.scope.target_id == "526403581"
    assert message.scope.bot_id == "9000"
    assert message.user_name == "小明"
    assert message.scope != replace(message.scope, platform_id="p2")


def test_only_direct_bot_at_counts(onebot_event):
    from astrbot.api.message_components import At, AtAll, Plain, Reply

    for component, expected in [
        (At(qq="9000"), True),
        (At(qq="2000"), False),
        (AtAll(), False),
        (Reply(id="q", sender_id="9000"), False),
    ]:
        onebot_event.message_obj.message = [component, Plain("我吃什么")]
        assert extract_message(onebot_event).mentioned_bot is expected
