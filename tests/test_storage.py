import json

import pytest

from keyword_reply.policy import empty_state
from keyword_reply.storage import StateStore


async def test_roundtrip_and_old_revision_cannot_overwrite(tmp_path):
    store = StateStore(tmp_path / "state.json")
    state = await store.load()
    assert state == empty_state()
    state.update(revision=2, global_paused=True)
    await store.save(state)
    await store.save(dict(state, revision=1, global_paused=False))
    assert (await StateStore(store.path).load())["global_paused"] is True


@pytest.mark.parametrize("content", ["{broken", '{"version":99}', "[]"])
async def test_corruption_preserved_and_auto_reply_paused(tmp_path, content):
    path = tmp_path / "state.json"
    path.write_text(content, encoding="utf-8")
    state = await StateStore(path).load()
    assert state["global_paused"] is True
    assert list(tmp_path.glob("state.json.corrupt-*"))


async def test_replace_failure_keeps_old_file(tmp_path, monkeypatch):
    store = StateStore(tmp_path / "state.json")
    state = empty_state()
    await store.save(state)

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr("keyword_reply.storage.os.replace", fail)
    with pytest.raises(OSError):
        await store.save(dict(state, revision=1, global_paused=True))
    assert json.loads(store.path.read_text(encoding="utf-8"))["global_paused"] is False
    assert not list(tmp_path.glob("*.tmp"))


async def test_temp_creation_failure_preserves_existing_state(tmp_path, monkeypatch):
    store = StateStore(tmp_path / "state.json")
    await store.save(empty_state())

    def fail(*args, **kwargs):
        raise OSError("no space")

    monkeypatch.setattr("keyword_reply.storage.tempfile.mkstemp", fail)
    with pytest.raises(OSError):
        await store.save(dict(empty_state(), revision=1, global_paused=True))
    assert json.loads(store.path.read_text(encoding="utf-8"))["global_paused"] is False
