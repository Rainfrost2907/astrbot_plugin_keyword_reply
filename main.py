import hashlib
import os
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .keyword_reply.astrbot_adapter import extract_message
from .keyword_reply.commands import execute_command, limit_report, parse_command
from .keyword_reply.engine import compile_snapshot
from .keyword_reply.models import ConfigError
from .keyword_reply.policy import RuntimePolicy
from .keyword_reply.service import ReplyService
from .keyword_reply.storage import StateStore


class KeywordReplyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context, config)
        self.config = config
        self.service = None

    async def initialize(self):
        config_path = getattr(self.config, "config_path", None)
        identity = os.path.normcase(str(Path(config_path).resolve())) if config_path else "default"
        profile = hashlib.sha256(identity.encode()).hexdigest()[:16]
        path = (
            Path(get_astrbot_plugin_data_path())
            / "astrbot_plugin_keyword_reply"
            / profile
            / "state.json"
        )
        issues = ()
        try:
            snapshot = compile_snapshot(dict(self.config), "initial")
        except ConfigError as exc:
            snapshot = compile_snapshot({"enabled": False}, "invalid")
            issues = exc.issues
        self.service = ReplyService(
            snapshot,
            RuntimePolicy(),
            StateStore(path),
            config_path=config_path,
            preserve_state=bool(issues),
        )
        await self.service.initialize()
        if issues:
            self.service.config_issues = issues
            self.service.last_error = "初始配置无效，自动回复已关闭"
            logger.warning("keyword_reply initial_config_invalid")

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.ALL, priority=10)
    async def on_message(self, event: AstrMessageEvent):
        if not self.service or event.get_extra("keyword_reply.management_event"):
            return
        head = event.get_message_str().lstrip().split(maxsplit=1)
        if head and head[0] in {"kwr", "关键词回复"}:
            return
        message = extract_message(event)
        await self.service.handle(message, lambda text: event.send(event.plain_result(text)))

    async def terminate(self):
        if self.service:
            await self.service.close()

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.command("kwr", alias={"关键词回复"}, priority=100)
    async def manage(self, event: AstrMessageEvent):
        event.set_extra("keyword_reply.management_event", True)
        if not self.service:
            await event.send(event.plain_result("关键词回复尚未初始化。"))
            return
        message = extract_message(event)
        if not event.is_admin():
            response = "仅 AstrBot 配置中的机器人管理员可以使用关键词回复管理命令。"
        else:
            normalized = event.get_message_str().lstrip()
            name = normalized.split(maxsplit=1)[0]
            index = message.text.find(name)
            body = message.text[index:] if index >= 0 else normalized
            try:
                command = parse_command(body)
                response = await execute_command(self.service, command, message, True)
            except ValueError as exc:
                response = str(exc)
        await event.send(event.plain_result(limit_report(response)))
