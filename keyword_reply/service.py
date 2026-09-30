import asyncio
import hashlib
import json
import logging
import time
from dataclasses import replace
from pathlib import Path

from .engine import compile_snapshot, evaluate
from .models import ConfigError, HandleResult, SendOutcome
from .policy import RuntimePolicy, cursor_id, scope_id

logger = logging.getLogger(__name__)
REASONS = {
    "disabled": "面板或运行开关禁用",
    "wrong_platform": "平台不符",
    "wrong_chat_type": "聊天类型不符",
    "scope_denied": "群或用户范围不符",
    "needs_at": "需要直接 @机器人",
    "excluded": "包含排除词",
    "no_match": "未匹配",
    "invalid_rule": "规则无效",
    "empty_reply": "回复为空或超长",
    "duplicate": "重复事件",
    "group_cooldown": "群冷却中",
    "rule_cooldown": "群规则冷却中",
    "user_cooldown": "用户规则冷却中",
    "probability": "未通过概率抽样",
    "busy": "正在处理其他消息",
    "regex_timeout": "正则超时",
    "budget_exhausted": "匹配预算耗尽",
    "send_failed": "发送失败",
    "matched": "已匹配",
    "eligible": "可参与回复选择",
    "input_too_long": "消息过长",
    "sent": "已发送",
    "ignored_prefix": "正文命中忽略的命令前缀",
    "self_message": "忽略机器人自身消息",
}


class ReplyService:
    def __init__(
        self, snapshot, policy, store, clock=time.monotonic, config_path=None, preserve_state=False
    ):
        self.snapshot = snapshot
        self.policy = policy
        self.store = store
        self.clock = clock
        self.config_path = Path(config_path) if config_path else None
        self.config_issues = snapshot.issues
        self.last_error = ""
        self._last_log = {}
        self._permits = asyncio.Queue(maxsize=2)
        for i in range(2):
            self._permits.put_nowait(i)
        self._persist_lock = asyncio.Lock()
        self._config_lock = asyncio.Lock()
        self._workers = set()
        self._handles = set()
        self._background = []
        self._closed = False
        self._saved_revision = -1
        self._preserve_state = preserve_state
        self._retain_rules()

    def _retain_rules(self):
        if not self._preserve_state:
            ids = {r.rule.id for r in self.snapshot.rules} | {
                i.rule_id for i in self.snapshot.issues if i.rule_id
            }
            self.policy.retain_rules(ids)

    async def initialize(self):
        self.policy.restore_persistent(await self.store.load())
        self._retain_rules()
        self.last_error = self.store.warning
        self._background.append(asyncio.create_task(self._flush_loop()))
        if self.config_path:
            self._background.append(asyncio.create_task(self._watch_loop()))

    def _log_error(self, code, rule_id="*"):
        key = (code, rule_id)
        now = self.clock()
        if now - self._last_log.get(key, float("-inf")) >= 60:
            logger.warning("keyword_reply rule=%s error=%s", rule_id, code)
            self._last_log[key] = now
        if len(self._last_log) > 1000:
            self._last_log.pop(next(iter(self._last_log)))

    async def _evaluate(self, snapshot, message):
        try:
            token = self._permits.get_nowait()
        except asyncio.QueueEmpty:
            return None
        worker = asyncio.create_task(
            asyncio.to_thread(evaluate, snapshot, message, clock=self.clock)
        )
        self._workers.add(worker)
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            await worker
            raise
        finally:
            self._workers.discard(worker)
            self._permits.put_nowait(token)

    async def handle(self, message, send):
        if self._closed:
            return HandleResult("disabled")
        task = asyncio.create_task(self._handle(message, send))
        self._handles.add(task)
        try:
            return await task
        finally:
            self._handles.discard(task)

    async def _handle(self, message, send):
        snapshot = self.snapshot
        reason = self.entry_reason(snapshot, message)
        if reason:
            return HandleResult("scope_denied" if reason == "self_message" else "no_match")
        evaluation = await self._evaluate(snapshot, message)
        if evaluation is None:
            self.policy.record("busy")
            return HandleResult("busy")
        for trace in evaluation.traces:
            self.policy.record(trace.reason, trace.rule_id)
            if trace.reason in {"regex_timeout", "budget_exhausted"}:
                self._log_error(trace.reason, trace.rule_id)
        if not evaluation.candidates:
            return HandleResult(evaluation.traces[-1].reason if evaluation.traces else "no_match")
        reservation = await self.policy.reserve(snapshot, message, evaluation)
        if reservation is None:
            return HandleResult(self.policy.last_reason(message))
        outcomes = []
        try:
            for delivery in reservation.deliveries:
                # Mark before awaiting: cancellation/unknown network outcome must retain dedup.
                outcomes.append(SendOutcome(delivery.rule_id, True, False, "send_failed"))
                try:
                    await asyncio.wait_for(send(delivery.text), timeout=15)
                except Exception:
                    self._log_error("send_failed", delivery.rule_id)
                else:
                    outcomes[-1] = SendOutcome(delivery.rule_id, True, True, None)
        finally:
            await self.policy.complete(reservation, tuple(outcomes))
        sent = tuple(o.rule_id for o in outcomes if o.success)
        return HandleResult("sent" if sent else "send_failed", sent)

    async def apply_config(self, raw, revision):
        async with self._config_lock:
            try:
                snapshot = await asyncio.to_thread(compile_snapshot, raw, revision)
            except ConfigError as exc:
                self.config_issues = exc.issues
                self.last_error = "新配置无效，继续使用上次有效配置"
                raise
            self.snapshot = snapshot
            self.config_issues = snapshot.issues
            self.last_error = ""
            self._preserve_state = False
            self._retain_rules()
            return snapshot.issues

    async def reload_config(self):
        if not self.config_path:
            raise ValueError("没有可读取的 AstrBot 配置路径")
        text = await asyncio.to_thread(self.config_path.read_text, encoding="utf-8-sig")
        raw = json.loads(text)
        return await self.apply_config(raw, hashlib.sha256(text.encode()).hexdigest()[:16])

    async def update_runtime(self, action, rule_id, scope, global_scope):
        if rule_id and rule_id not in {r.rule.id for r in self.snapshot.rules}:
            raise ValueError("规则不存在或配置无效")
        async with self._persist_lock:
            proposal = RuntimePolicy()
            proposal.restore_persistent(self.policy.export_persistent())
            proposal.change_controls(action, rule_id, scope, global_scope)
            data = proposal.export_persistent()
            await self.store.save(data)
            self.policy.apply_controls(data)
            self._retain_rules()
            self._saved_revision = data["revision"]

    async def flush(self):
        async with self._persist_lock:
            data = self.policy.export_persistent()
            if data["revision"] != self._saved_revision:
                await self.store.save(data)
                self._saved_revision = data["revision"]

    async def diagnose(self, message, rule_id=None):
        snapshot = self.snapshot
        reason = self.entry_reason(snapshot, message)
        if reason:
            return "总体结论：不自动回复，" + REASONS[reason] + "。测试没有状态副作用。"
        if rule_id:
            selected = tuple(r for r in snapshot.rules if r.rule.id == rule_id)
            if not selected:
                issues = [i for i in self.config_issues if i.rule_id == rule_id]
                return "规则不存在或无效\n" + "\n".join(f"{i.path}: {i.message}" for i in issues)
            snapshot = replace(snapshot, rules=selected)
        evaluation = await self._evaluate(snapshot, message)
        if evaluation is None:
            return "匹配工作繁忙，请稍后测试（不会消耗冷却）。"
        lines = [
            "规则测试：只展示结果，不发送候选、不消耗冷却。",
            f"选择模式：{snapshot.settings.selection_mode}",
        ]
        lines.extend(
            f"{t.rule_id}: {REASONS.get(t.reason, t.reason)} {t.detail}" for t in evaluation.traces
        )
        preview = {t.rule_id: t for t in self.policy.preview(snapshot, message, evaluation)}
        for candidate in evaluation.candidates:
            rule = candidate.rule
            lines.append(
                f"{rule.id} 捕获={candidate.match.keyword!r} 匹配={candidate.match.text!r} 分组={candidate.match.groups!r}"
            )
            lines.append(f"候选：{candidate.replies!r}")
            trace = preview[rule.id]
            lines.append(f"门槛：{REASONS.get(trace.reason, trace.reason)}；{trace.detail}")
            if rule.reply_mode == "round_robin":
                index = self.policy._data["cursors"].get(
                    cursor_id(message.scope, rule.id), 0
                ) % len(candidate.replies)
                lines.append(f"轮询下一项：{index + 1}")
        lines.extend(
            f"配置错误 {i.path}: {i.message}"
            for i in snapshot.issues
            if not rule_id or i.rule_id == rule_id
        )
        return "\n".join(lines)

    @staticmethod
    def entry_reason(snapshot, message):
        if message.user_id == message.scope.bot_id:
            return "self_message"
        if any(
            message.text.lstrip().startswith(p) for p in snapshot.settings.ignore_command_prefixes
        ):
            return "ignored_prefix"
        head = message.text.lstrip().split(maxsplit=1)
        if head and head[0] in {"kwr", "关键词回复"}:
            return "ignored_prefix"
        return None

    async def _flush_loop(self):
        while True:
            await asyncio.sleep(30)
            try:
                await self.flush()
            except OSError:
                self.last_error = "状态保存失败，等待重试"
                self._log_error("state_save_failed")

    async def _watch_loop(self):
        stamp = None
        while True:
            try:
                info = await asyncio.to_thread(self.config_path.stat)
                current = (info.st_mtime_ns, info.st_size)
                if current != stamp:
                    await self.reload_config()
                    stamp = current
            except (OSError, ValueError):
                self.last_error = "配置文件更新失败，保留上次有效配置并等待重试"
                self._log_error("config_reload_failed")
            await asyncio.sleep(2)

    async def close(self):
        if self._closed:
            return
        self._closed = True
        tasks = [*self._background, *self._handles]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        await self.flush()

    def status(self, message):
        return {
            "revision": self.snapshot.revision,
            "scope": scope_id(message.scope),
            "enabled": self.snapshot.settings.enabled,
            "runtime_disabled": bool(self.policy.runtime_reason(message.scope)),
            "valid_rules": len(self.snapshot.rules),
            "issues": len(self.config_issues),
            "inflight": len(self.policy._active),
            "dedup_entries": len(self.policy._dedup),
            "cooldown_entries": len(self.policy._cooldowns),
            "last_error": self.last_error,
        }
