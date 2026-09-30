import asyncio
import random
from dataclasses import replace

import pytest

from keyword_reply.models import ConfigError
from keyword_reply.policy import RuntimePolicy
from keyword_reply.service import ReplyService
from keyword_reply.storage import StateStore


@pytest.fixture
def service(snapshot, tmp_path):
    return ReplyService(
        snapshot,
        RuntimePolicy(lambda: 100, random.Random(1)),
        StateStore(tmp_path / "state.json"),
        clock=lambda: 100,
    )


async def test_success_and_duplicate(service, message):
    sent = []

    async def send(text):
        sent.append(text)

    assert (await service.handle(message, send)).sent_rule_ids == ("echo",)
    assert (await service.handle(message, send)).reason == "duplicate"
    assert sent == ["是啊吃什么"]


async def test_send_failure_does_not_change_controls(service, message):
    before = service.policy.export_persistent()

    async def broken(text):
        raise OSError("OneBot unavailable")

    result = await service.handle(message, broken)
    assert result.sent_rule_ids == () and result.reason == "send_failed"
    assert service.policy.export_persistent() == before


async def test_reload_preserves_snapshot_on_global_error(service):
    old = service.snapshot
    with pytest.raises(ConfigError):
        await service.apply_config({"enabled": "false"}, "r2")
    assert service.snapshot is old


async def test_temporarily_invalid_rule_keeps_runtime_disable(service, message, raw_rule):
    await service.update_runtime("off", "echo")
    broken = dict(raw_rule, pattern="(", match_type="regex")
    await service.apply_config({"rules": [broken]}, "bad_rule")
    assert service.policy.export_persistent()["global_disabled"] == ["echo"]
    await service.apply_config({"rules": [raw_rule]}, "repaired")
    assert service.policy.runtime_reason(message.scope, "echo") == "disabled"


async def test_diagnose_no_side_effects(service, message):
    before = (
        service.policy.export_persistent(),
        service.policy.rng.getstate(),
        dict(service.policy.stats),
    )
    report = await service.diagnose(message, "echo")
    assert "吃" in report and "是啊吃什么" in report
    assert (
        service.policy.export_persistent(),
        service.policy.rng.getstate(),
        dict(service.policy.stats),
    ) == before
    assert not service.store.path.exists()


async def test_management_save_failure_rolls_back(service, message, monkeypatch):
    async def fail(data):
        raise OSError("disk full")

    monkeypatch.setattr(service.store, "save", fail)
    with pytest.raises(OSError):
        await service.update_runtime("pause")
    assert service.policy.runtime_reason(message.scope) is None


async def test_runtime_pause_persists_and_applies_to_all_groups(service, message):
    await service.update_runtime("pause")
    data = await service.store.load()
    fresh = RuntimePolicy()
    fresh.restore_persistent(data)
    assert fresh.runtime_reason(message.scope) == "disabled"
    assert fresh.runtime_reason(replace(message.scope, target_id="other")) == "disabled"


async def test_busy_pool_does_not_queue(service, message):
    tokens = [service._permits.get_nowait(), service._permits.get_nowait()]

    async def send(text):
        raise AssertionError("should not send")

    assert (await service.handle(message, send)).reason == "busy"
    for token in tokens:
        service._permits.put_nowait(token)


async def test_cancellation_releases_reservation(service, message):
    started = asyncio.Event()

    async def wait_send(text):
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(service.handle(message, wait_send))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not service.policy._active
    assert service.policy._dedup
