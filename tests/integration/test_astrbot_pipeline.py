import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from keyword_reply.policy import RuntimePolicy
from keyword_reply.service import ReplyService
from keyword_reply.storage import StateStore


@pytest.fixture
def plugin(snapshot, tmp_path):
    package = types.ModuleType("test_keyword_plugin")
    package.__path__ = [str(Path(__file__).resolve().parents[2])]
    sys.modules.setdefault(package.__name__, package)
    main = importlib.import_module("test_keyword_plugin.main")
    obj = main.KeywordReplyPlugin(SimpleNamespace(), {})
    obj.service = ReplyService(snapshot, RuntimePolicy(), StateStore(tmp_path / "state.json"))
    return obj


@pytest.mark.parametrize(
    "behavior,agent_calls", [("success", 0), ("miss", 1), ("fail", 1), ("cooldown", 1)]
)
async def test_real_process_stage_keeps_other_handlers(plugin, onebot_event, behavior, agent_calls):
    from astrbot.api.message_components import Plain
    from astrbot.core.pipeline.process_stage.stage import ProcessStage, StarRequestSubStage
    from astrbot.core.star.star import star_map
    from astrbot.core.star.star_handler import EventType, StarHandlerMetadata

    other_calls = []
    llm_calls = []

    async def other(event):
        other_calls.append(event)

    class Agent:
        async def process(self, event):
            llm_calls.append(event)
            yield

    onebot_event.is_at_or_wake_command = True
    if behavior == "miss":
        onebot_event.message_obj.message = [Plain("无关键词")]
    if behavior == "fail":
        onebot_event.bot.fail = True
    if behavior == "cooldown":
        await plugin.on_message(onebot_event)
        onebot_event.message_obj.message_id = "m2"
        onebot_event._has_send_oper = False  # reset the fixture between two incoming events
    module = plugin.__class__.__module__
    star_map[module].star_cls = plugin
    handlers = [
        StarHandlerMetadata(
            EventType.AdapterMessageEvent, "test_auto", "on_message", module, plugin.on_message, []
        ),
        StarHandlerMetadata(
            EventType.AdapterMessageEvent, "test_other", "other", module, other, []
        ),
    ]
    onebot_event.set_extra("activated_handlers", handlers)
    stage = ProcessStage()
    stage.ctx = SimpleNamespace(astrbot_config={"provider_settings": {"enable": True}})
    stage.star_request_sub_stage = StarRequestSubStage()
    stage.agent_sub_stage = Agent()
    async for _ in stage.process(onebot_event):
        pass
    assert len(other_calls) == 1
    assert len(llm_calls) == agent_calls
    assert not onebot_event.is_stopped()


async def test_admin_role_and_raw_command_body(plugin, onebot_event):
    from astrbot.api.message_components import Plain

    onebot_event.message_str = "kwr test echo 我  吃什么"
    onebot_event.message_obj.message = [Plain("/kwr test echo 我  吃什么")]
    onebot_event.role = "member"
    await plugin.manage(onebot_event)
    assert "仅 AstrBot" in onebot_event.bot.sent[-1]["message"][0]["data"]["text"]
    assert onebot_event.get_extra("keyword_reply.management_event")
    onebot_event.role = "admin"
    await plugin.manage(onebot_event)
    assert "是啊  吃什么" in onebot_event.bot.sent[-1]["message"][0]["data"]["text"]
