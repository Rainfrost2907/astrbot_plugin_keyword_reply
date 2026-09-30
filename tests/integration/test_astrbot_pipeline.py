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
    "behavior,agent_calls",
    [("success", 0), ("miss", 1), ("fail", 1), ("cooldown", 1), ("timeout", 1)],
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
    if behavior == "timeout":
        from keyword_reply.engine import compile_snapshot

        plugin.service.snapshot = compile_snapshot(
            {
                "rules": [
                    {
                        "id": "slow",
                        "name": "slow",
                        "match_type": "regex",
                        "pattern": "(x+)+$",
                        "replies": ["no"],
                    }
                ]
            },
            "timeout",
        )
        onebot_event.message_obj.message = [Plain("x" * 4095 + "!")]
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


@pytest.mark.parametrize("text,expected", [("我吃什么", "on_message"), ("/kwr status", "manage")])
async def test_real_waking_stage_activates_registered_entry(
    plugin, onebot_event, text, expected, monkeypatch
):
    from copy import deepcopy

    from astrbot.api.message_components import Plain
    from astrbot.core.config.default import DEFAULT_CONFIG
    from astrbot.core.pipeline.waking_check.stage import WakingCheckStage
    from astrbot.core.star.session_plugin_manager import sp
    from astrbot.core.star.star import star_map
    from astrbot.core.star.star_handler import star_handlers_registry

    module = plugin.__class__.__module__
    metadata = star_map[module]
    metadata.name = "astrbot_plugin_keyword_reply"
    metadata.star_cls = plugin
    for handler in star_handlers_registry.get_handlers_by_module_name(module):
        handler.handler = getattr(plugin, handler.handler_name)
    config = deepcopy(DEFAULT_CONFIG)
    config.update(wake_prefix=["/"], admins_id=["2000"], plugin_set=[metadata.name])

    async def empty_preferences(**kwargs):
        return {}

    monkeypatch.setattr(sp, "get_async", empty_preferences)
    stage = WakingCheckStage()
    await stage.initialize(
        SimpleNamespace(astrbot_config=config, db_helper=None, astrbot_config_id="test")
    )
    onebot_event.message_str = text
    onebot_event.message_obj.message = [Plain(text)]
    await stage.process(onebot_event)
    handlers = onebot_event.get_extra("activated_handlers")
    assert expected in {h.handler_name for h in handlers}
    assert not onebot_event.is_stopped()
    for handler in handlers:
        await handler.handler(onebot_event)
    assert onebot_event.bot.sent
    assert onebot_event.role == "admin"
