import asyncio
from dataclasses import replace

import pytest

from keyword_reply.commands import execute_command, parse_command
from keyword_reply.config import load_config
from keyword_reply.engine import compile_snapshot
from keyword_reply.models import ConfigError
from keyword_reply.policy import RuntimePolicy
from keyword_reply.service import ReplyService
from keyword_reply.storage import StateStore


def test_huge_numeric_input_is_config_error():
    with pytest.raises(ConfigError):
        load_config({"group_cooldown_seconds": 10**1000})


async def test_deleted_rule_during_command_save(snapshot, message):
    started, release = asyncio.Event(), asyncio.Event()

    class Store:
        async def save(self, data):
            started.set()
            await release.wait()

    service = ReplyService(snapshot, RuntimePolicy(), Store())
    task = asyncio.create_task(
        execute_command(service, parse_command("kwr off echo"), message, True)
    )
    await started.wait()
    await service.apply_config({"rules": []}, "new")
    release.set()
    assert "配置已变化" in await task
    assert not service.policy.export_persistent()["global_disabled"]


async def test_diagnostics_explain_ignored_prefix(raw_rule, message, tmp_path):
    snapshot = compile_snapshot(
        {"rules": [dict(raw_rule, match_type="contains", keywords=["hello"])]}, "r"
    )
    service = ReplyService(snapshot, RuntimePolicy(), StateStore(tmp_path / "state.json"))
    report = await service.diagnose(replace(message, text="/hello"))
    assert "命令前缀" in report
    assert "可参与回复选择" not in report
