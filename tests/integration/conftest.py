import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRAMEWORK = ROOT / ".integration" / "AstrBot"
if FRAMEWORK.exists():
    sys.path.insert(0, str(FRAMEWORK))
os.environ.setdefault("ASTRBOT_ROOT", str(ROOT / ".integration" / "runtime"))
os.environ["ASTRBOT_DISABLE_METRICS"] = "1"


@pytest.fixture
def onebot_event():
    from astrbot.api.message_components import Plain
    from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember, MessageType
    from astrbot.core.platform.platform_metadata import PlatformMetadata
    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
        AiocqhttpMessageEvent,
    )

    class Bot:
        def __init__(self):
            self.sent = []
            self.fail = False

        async def send_group_msg(self, **kwargs):
            if self.fail:
                raise OSError("test send failure")
            self.sent.append(kwargs)

    obj = AstrBotMessage()
    obj.type = MessageType.GROUP_MESSAGE
    obj.self_id = "9000"
    obj.group_id = "526403581"
    obj.session_id = "526403581"
    obj.message_id = "m1"
    obj.sender = MessageMember("2000", "小明")
    obj.message = [Plain("我吃什么")]
    obj.message_str = "我吃什么"
    obj.raw_message = None
    return AiocqhttpMessageEvent(
        obj.message_str,
        obj,
        PlatformMetadata("aiocqhttp", "test", "p1"),
        "526403581",
        Bot(),
    )
