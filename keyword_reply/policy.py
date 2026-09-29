"""Event-loop-owned policy: reserve and complete have no suspension points."""

import copy
import json
import random
import time
import uuid
from collections import Counter, OrderedDict
from dataclasses import astuple

from .models import Delivery, Reservation, Trace

CAPACITY = 10000


def scope_id(scope):
    return json.dumps(astuple(scope), ensure_ascii=False, separators=(",", ":"))


def cursor_id(scope, rule_id):
    return json.dumps((*astuple(scope), rule_id), ensure_ascii=False, separators=(",", ":"))


def empty_state():
    return {
        "version": 1,
        "revision": 0,
        "global_paused": False,
        "global_disabled": [],
        "scopes": {},
        "cursors": {},
    }


def validate_persistent(data):
    if not isinstance(data, dict) or set(data) != set(empty_state()):
        raise ValueError("状态结构无效")
    if type(data["version"]) is not int or data["version"] != 1:
        raise ValueError("状态版本不受支持")
    if (
        type(data["revision"]) is not int
        or data["revision"] < 0
        or type(data["global_paused"]) is not bool
    ):
        raise ValueError("状态字段无效")

    def ids(value):
        return (
            isinstance(value, list)
            and len(value) <= 500
            and all(isinstance(x, str) and 0 < len(x) <= 64 for x in value)
        )

    if not ids(data["global_disabled"]):
        raise ValueError("禁用规则集合无效")
    for section, size in (("scopes", 4), ("cursors", 5)):
        mapping = data[section]
        if not isinstance(mapping, dict) or len(mapping) > CAPACITY:
            raise ValueError("会话状态超过容量或类型无效")
        for key, value in mapping.items():
            parts = json.loads(key)
            if (
                not isinstance(parts, list)
                or len(parts) != size
                or not all(isinstance(p, str) and 0 < len(p) <= 256 for p in parts)
            ):
                raise ValueError("会话键无效")
            if section == "scopes":
                if (
                    not isinstance(value, dict)
                    or set(value) != {"paused", "disabled"}
                    or type(value["paused"]) is not bool
                    or not ids(value["disabled"])
                ):
                    raise ValueError("会话开关无效")
            elif type(value) is not int or value < 0:
                raise ValueError("轮询游标无效")


class RuntimePolicy:
    def __init__(self, clock=time.monotonic, rng=None):
        self.clock = clock
        self.rng = rng if rng is not None else random.Random()
        self._data = empty_state()
        self._active = {}
        self._dedup = OrderedDict()
        self._cooldowns = OrderedDict()
        self._reasons = OrderedDict()
        self._live_ids = None
        self.stats = Counter()
        self.rule_stats = {}

    def record(self, reason, rule_id=None):
        self.stats[reason] += 1
        if rule_id and rule_id != "*" and (self._live_ids is None or rule_id in self._live_ids):
            self.rule_stats.setdefault(rule_id, Counter())[reason] += 1

    def _put(self, cache, key, value):
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > CAPACITY:
            cache.popitem(last=False)
            self.stats["cache_evicted"] += 1

    def _reject(self, message, reason):
        self._put(self._reasons, message.scope, reason)
        self.record(reason)
        return None

    def last_reason(self, message):
        return self._reasons.get(message.scope, "no_match")

    def runtime_reason(self, scope, rule_id=None):
        local = self._data["scopes"].get(scope_id(scope), {})
        if self._data["global_paused"] or local.get("paused", False):
            return "disabled"
        if rule_id is not None and (
            rule_id in self._data["global_disabled"] or rule_id in local.get("disabled", [])
        ):
            return "disabled"
        return None

    def _global_reason(self, snapshot, message, now):
        if not snapshot.settings.enabled or self.runtime_reason(message.scope):
            return "disabled"
        if message.message_id and self._dedup.get((message.scope, message.message_id), 0) > now:
            return "duplicate"
        if message.scope in self._active or len(self._active) >= CAPACITY:
            return "busy"
        if self._cooldowns.get(("group", message.scope), 0) > now:
            return "group_cooldown"
        return None

    def _rule_reason(self, rule, message, now):
        if not rule.enabled or self.runtime_reason(message.scope, rule.id):
            return "disabled"
        if self._cooldowns.get(("rule", message.scope, rule.id), 0) > now:
            return "rule_cooldown"
        if self._cooldowns.get(("user", message.scope, rule.id, message.user_id), 0) > now:
            return "user_cooldown"
        return None

    async def reserve(self, snapshot, message, evaluation):
        now = self.clock()
        for cache in (self._dedup, self._cooldowns):
            for key in [key for key, expiry in cache.items() if expiry <= now]:
                del cache[key]
        reason = self._global_reason(snapshot, message, now)
        if reason:
            return self._reject(message, reason)
        if evaluation.exhausted:
            return self._reject(message, "budget_exhausted")
        eligible = []
        last_reason = "no_match"
        for candidate in evaluation.candidates:
            rule = candidate.rule
            reason = self._rule_reason(rule, message, now)
            if reason is None and (
                rule.probability == 0
                or (rule.probability < 1 and self.rng.random() >= rule.probability)
            ):
                reason = "probability"
            if reason:
                last_reason = reason
                self.record(reason, rule.id)
            else:
                eligible.append(candidate)
        if not eligible:
            return self._reject(message, last_reason)
        mode = snapshot.settings.selection_mode
        chosen = (
            [self.rng.choice(eligible)]
            if mode == "random"
            else eligible[: snapshot.settings.max_replies if mode == "all" else 1]
        )
        deliveries = []
        for candidate in chosen:
            rule = candidate.rule
            index, next_cursor = 0, None
            if rule.reply_mode == "random":
                index = self.rng.randrange(len(candidate.replies))
            elif rule.reply_mode == "round_robin":
                index = self._data["cursors"].get(cursor_id(message.scope, rule.id), 0) % len(
                    candidate.replies
                )
                next_cursor = (index + 1) % len(candidate.replies)
            deliveries.append(Delivery(rule.id, candidate.replies[index], next_cursor))
        result = Reservation(
            uuid.uuid4().hex,
            message.scope,
            message.user_id,
            message.message_id,
            tuple(deliveries),
            snapshot.revision,
        )
        self._active[message.scope] = (result, snapshot, {c.rule.id: c.rule for c in chosen})
        if not message.message_id:
            self.stats["missing_message_id"] += 1
        return result

    async def complete(self, reservation, outcomes):
        current = self._active.get(reservation.scope)
        if not current or current[0].token != reservation.token:
            return
        _, snapshot, rules = current
        now = self.clock()
        successful = {o.rule_id for o in outcomes if o.success and o.attempted}
        attempted = any(o.attempted for o in outcomes)
        try:
            if attempted and reservation.message_id:
                self._put(
                    self._dedup,
                    (reservation.scope, reservation.message_id),
                    now + snapshot.settings.dedup_ttl_seconds,
                )
            if successful and snapshot.settings.group_cooldown_seconds:
                self._put(
                    self._cooldowns,
                    ("group", reservation.scope),
                    now + snapshot.settings.group_cooldown_seconds,
                )
            for delivery in reservation.deliveries:
                if delivery.rule_id not in successful:
                    if any(o.rule_id == delivery.rule_id and o.attempted for o in outcomes):
                        self.record("send_failed", delivery.rule_id)
                    continue
                self.record("sent", delivery.rule_id)
                if self._live_ids is not None and delivery.rule_id not in self._live_ids:
                    continue
                rule = rules[delivery.rule_id]
                for key, seconds in (
                    (("rule", reservation.scope, rule.id), rule.group_rule_cooldown_seconds),
                    (
                        ("user", reservation.scope, rule.id, reservation.user_id),
                        rule.user_rule_cooldown_seconds,
                    ),
                ):
                    if seconds:
                        self._put(self._cooldowns, key, now + seconds)
                if delivery.next_cursor is not None:
                    cursors = self._data["cursors"]
                    key = cursor_id(reservation.scope, rule.id)
                    cursors.pop(key, None)
                    cursors[key] = delivery.next_cursor
                    while len(cursors) > CAPACITY:
                        del cursors[next(iter(cursors))]
                        self.stats["cursor_evicted"] += 1
                    self._data["revision"] += 1
        finally:
            self._active.pop(reservation.scope, None)

    def preview(self, snapshot, message, evaluation):
        now = self.clock()
        global_reason = self._global_reason(snapshot, message, now)
        traces = []
        for candidate in evaluation.candidates:
            reason = global_reason or self._rule_reason(candidate.rule, message, now)
            traces.append(
                Trace(
                    candidate.rule.id,
                    reason or "eligible",
                    f"正常通过概率 {candidate.rule.probability:g}",
                )
            )
        return tuple(traces)

    def export_persistent(self):
        return copy.deepcopy(self._data)

    def restore_persistent(self, data):
        validate_persistent(data)
        self._data = copy.deepcopy(data)

    def apply_controls(self, data):
        """Publish persisted controls without overwriting newer in-flight cursors."""
        for key in ("global_paused", "global_disabled", "scopes"):
            self._data[key] = copy.deepcopy(data[key])
        self._data["revision"] = max(self._data["revision"], data["revision"]) + 1

    def change_controls(self, action, rule_id, scope, global_scope):
        if action not in {"on", "off", "pause", "resume", "reset"}:
            raise ValueError("未知管理操作")
        if action in {"on", "off"} and not rule_id:
            raise ValueError("需要规则 ID")
        data = self.export_persistent()
        key = scope_id(scope)
        if global_scope:
            target = {"paused": data["global_paused"], "disabled": data["global_disabled"]}
        else:
            if key not in data["scopes"] and len(data["scopes"]) >= CAPACITY:
                raise ValueError("会话管理状态已达 10000 条上限")
            target = data["scopes"].setdefault(key, {"paused": False, "disabled": []})
        if action == "reset":
            target.update(paused=False, disabled=[])
        elif action in {"pause", "resume"}:
            target["paused"] = action == "pause"
        elif action == "off":
            target["disabled"] = sorted(set(target["disabled"]) | {rule_id})
        elif action == "on":
            target["disabled"] = [x for x in target["disabled"] if x != rule_id]
        if global_scope:
            data["global_paused"], data["global_disabled"] = target["paused"], target["disabled"]
        elif not target["paused"] and not target["disabled"]:
            data["scopes"].pop(key, None)
        data["revision"] += 1
        validate_persistent(data)
        self._data = data

    def retain_rules(self, ids):
        self._live_ids = set(ids)
        before = self.export_persistent()
        self._data["global_disabled"] = [x for x in self._data["global_disabled"] if x in ids]
        for value in self._data["scopes"].values():
            value["disabled"] = [x for x in value["disabled"] if x in ids]
        self._data["cursors"] = {
            k: v for k, v in self._data["cursors"].items() if json.loads(k)[-1] in ids
        }
        self.rule_stats = {k: v for k, v in self.rule_stats.items() if k in ids}
        for key in list(self._cooldowns):
            if key[0] != "group" and key[2] not in ids:
                del self._cooldowns[key]
        if self._data != before:
            self._data["revision"] += 1
