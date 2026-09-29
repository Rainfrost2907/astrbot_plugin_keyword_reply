import asyncio
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from .policy import empty_state, validate_persistent


class StateStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = asyncio.Lock()
        self._revision = -1
        self.warning = ""

    async def _run(self, operation, *args):
        async with self._lock:
            task = asyncio.create_task(asyncio.to_thread(operation, *args))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise

    async def load(self) -> dict:
        return await self._run(self._load)

    def _load(self):
        if not self.path.exists():
            return empty_state()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            validate_persistent(data)
            self._revision = data["revision"]
            return data
        except (ValueError, TypeError, KeyError):
            backup = self.path.with_name(f"{self.path.name}.corrupt-{time.time_ns()}")
            shutil.copy2(self.path, backup)
            self.warning = "运行状态损坏，已保存备份并暂停自动回复；使用 /kwr resume global 恢复"
            state = empty_state()
            state["global_paused"] = True
            return state

    async def save(self, data: dict) -> None:
        validate_persistent(data)
        # Snapshot before awaiting: later mutations cannot change the bytes being committed.
        text = json.dumps(data, ensure_ascii=False, indent=2)
        await self._run(self._save, text, data["revision"])

    def _save(self, text, revision):
        if revision < self._revision:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix="state-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            self._revision = revision
        finally:
            if os.path.exists(name):
                os.unlink(name)
