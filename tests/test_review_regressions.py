import asyncio
from dataclasses import replace

import pytest

from keyword_reply.commands import execute_command, parse_command
from keyword_reply.config import load_config
from keyword_reply.engine import compile_snapshot, evaluate
from keyword_reply.models import ConfigError
from keyword_reply.policy import RuntimePolicy, scope_id
from keyword_reply.service import ReplyService
from keyword_reply.storage import StateStore


def test_search_skips_whitespace_capture(raw_rule, message):
    snapshot = compile_snapshot({"rules": [dict(raw_rule, match_scope="search")]}, "r")
    result = evaluate(snapshot, replace(message, text="我   什么，我吃什么"))
    assert result.candidates[0].match.keyword == "吃"


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
    assert not service.policy.export_persistent()["scopes"]


def test_removed_disabled_rule_prunes_empty_scope(message):
    policy = RuntimePolicy()
    policy.change_controls("off", "gone", message.scope, False)
    policy.retain_rules(set())
    assert scope_id(message.scope) not in policy.export_persistent()["scopes"]


async def test_diagnostics_explain_ignored_prefix(raw_rule, message, tmp_path):
    snapshot = compile_snapshot(
        {"rules": [dict(raw_rule, match_type="contains", keywords=["hello"])]}, "r"
    )
    service = ReplyService(snapshot, RuntimePolicy(), StateStore(tmp_path / "state.json"))
    report = await service.diagnose(replace(message, text="/hello"))
    assert "命令前缀" in report
    assert "可参与回复选择" not in report


async def test_stats_rule_id_and_show_sources(snapshot, message, tmp_path):
    service = ReplyService(snapshot, RuntimePolicy(), StateStore(tmp_path / "state.json"))
    await service.update_runtime("off", "echo", message.scope, True)
    report = await execute_command(service, parse_command("kwr show echo"), message, True)
    assert "global" in report and "冷却" in report and "示例" in report
    assert "echo" in await execute_command(service, parse_command("kwr stats echo"), message, True)
