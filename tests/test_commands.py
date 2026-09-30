from dataclasses import replace

import pytest

from keyword_reply.commands import execute_command, parse_command
from keyword_reply.policy import RuntimePolicy
from keyword_reply.service import ReplyService
from keyword_reply.storage import StateStore


@pytest.fixture
def command_service(snapshot, tmp_path):
    return ReplyService(snapshot, RuntimePolicy(), StateStore(tmp_path / "state.json"))


def test_body_whitespace():
    parsed = parse_command("kwr test echo 我  吃什么\n第二行")
    assert parsed.text == "我  吃什么\n第二行"
    assert parsed.rule_id == "echo"


@pytest.mark.parametrize(
    "text,action,scope",
    [
        ("关键词回复 help", "help", "here"),
        ("kwr off echo global", "off", "global"),
        ("kwr resume", "resume", "here"),
        ("kwr testat all 我吃什么", "testat", "here"),
    ],
)
def test_commands(text, action, scope):
    command = parse_command(text)
    assert (command.action, command.scope) == (action, scope)


@pytest.mark.parametrize(
    "text",
    [
        "kwr list 0",
        "kwr off",
        "kwr pause somewhere",
        "kwr test echo",
        "kwr unknown",
        "kwr list 1 extra",
    ],
)
def test_invalid_parameters(text):
    with pytest.raises(ValueError):
        parse_command(text)


async def test_nonadmin_cannot_view_or_mutate(command_service, message):
    for text in ["kwr list", "kwr show echo", "kwr test all 我吃什么", "kwr pause global"]:
        assert "仅 AstrBot" in await execute_command(
            command_service, parse_command(text), message, False
        )
    assert not command_service.store.path.exists()


async def test_pause_resume_and_unknown_id(command_service, message):
    for action in ["pause", "resume"]:
        assert "已" in await execute_command(
            command_service, parse_command("kwr " + action), message, True
        )
    assert command_service.policy.runtime_reason(message.scope) is None
    assert "不存在" in await execute_command(
        command_service, parse_command("kwr off missing"), message, True
    )


async def test_diagnostics_are_readonly(command_service, message):
    policy = command_service.policy
    before = (
        policy.export_persistent(),
        policy.rng.getstate(),
        dict(policy.stats),
        dict(policy._dedup),
        dict(policy._cooldowns),
    )
    report = await execute_command(
        command_service, parse_command("kwr test all 我吃什么"), message, True
    )
    assert "是啊吃什么" in report
    assert before == (
        policy.export_persistent(),
        policy.rng.getstate(),
        dict(policy.stats),
        dict(policy._dedup),
        dict(policy._cooldowns),
    )
    assert not command_service.store.path.exists()


async def test_testat_simulates_at(command_service, message):
    compiled = command_service.snapshot.rules[0]
    command_service.snapshot = replace(
        command_service.snapshot,
        rules=(replace(compiled, rule=replace(compiled.rule, require_at=True)),),
    )
    assert "需要直接" in await execute_command(
        command_service, parse_command("kwr test all 我吃什么"), message, True
    )
    assert "是啊吃什么" in await execute_command(
        command_service, parse_command("kwr testat all 我吃什么"), message, True
    )
