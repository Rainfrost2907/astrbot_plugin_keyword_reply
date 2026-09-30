"""One reply per message; atomic cooldown, deduplication and simple global switches."""

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


def empty_state():
    return {"version": 2, "revision": 0, "global_paused": False, "global_disabled": []}


def validate_persistent(data):
    if not isinstance(data, dict) or set(data) != set(empty_state()):
        raise ValueError("状态结构无效")
    if type(data["version"]) is not int or data["version"] != 2:
        raise ValueError("状态版本不受支持")
    if (
        type(data["revision"]) is not int
        or data["revision"] < 0
        or type(data["global_paused"]) is not bool
    ):
        raise ValueError("状态字段无效")
    ids = data["global_disabled"]
    if (
        not isinstance(ids, list)
        or len(ids) > 500
        or not all(isinstance(x, str) and 0 < len(x) <= 64 for x in ids)
    ):
        raise ValueError("禁用规则集合无效")


class RuntimePolicy:
    def __init__(self, clock=time.monotonic, rng=None):
        self.clock = clock
        self.rng = rng if rng is not None else random.Random()
        self._data = empty_state()
        self._active = {}
        self._dedup = OrderedDict()
        self._cooldowns = OrderedDict()
        self._reasons = OrderedDict()
        self.stats = Counter()

    def record(self, reason, rule_id=None):
        self.stats[reason] += 1

    def _put(self, cache, key, value):
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > CAPACITY:
            cache.popitem(last=False)

    def _reject(self, message, reason):
        self._put(self._reasons, message.scope, reason)
        self.record(reason)
        return None

    def last_reason(self, message):
        return self._reasons.get(message.scope, "no_match")

    def runtime_reason(self, scope=None, rule_id=None):
        if self._data["global_paused"] or rule_id in self._data["global_disabled"]:
            return "disabled"
        return None

    def _global_reason(self, snapshot, message, now):
        if not snapshot.settings.enabled or self.runtime_reason():
            return "disabled"
        if message.message_id and self._dedup.get((message.scope, message.message_id), 0) > now:
            return "duplicate"
        if message.scope in self._active or len(self._active) >= CAPACITY:
            return "busy"
        if self._cooldowns.get(("group", message.scope), 0) > now:
            return "group_cooldown"
        return None

    async def reserve(self, snapshot, message, evaluation):
        now = self.clock()
        for cache in (self._dedup, self._cooldowns):
            for key in [k for k, expiry in cache.items() if expiry <= now]:
                del cache[key]
        reason = self._global_reason(snapshot, message, now)
        if reason:
            return self._reject(message, reason)
        if evaluation.exhausted:
            return self._reject(message, "budget_exhausted")
        for candidate in evaluation.candidates:
            if not candidate.rule.enabled or self.runtime_reason(rule_id=candidate.rule.id):
                continue
            delivery = Delivery(candidate.rule.id, self.rng.choice(candidate.replies))
            result = Reservation(
                uuid.uuid4().hex,
                message.scope,
                message.user_id,
                message.message_id,
                (delivery,),
                snapshot.revision,
            )
            self._active[message.scope] = (result, snapshot)
            return result
        return self._reject(message, "disabled" if evaluation.candidates else "no_match")

    async def complete(self, reservation, outcomes):
        current = self._active.get(reservation.scope)
        if not current or current[0].token != reservation.token:
            return
        snapshot = current[1]
        now = self.clock()
        try:
            if any(o.attempted for o in outcomes) and reservation.message_id:
                self._put(self._dedup, (reservation.scope, reservation.message_id), now + 120)
            success = any(o.success and o.attempted for o in outcomes)
            if success and snapshot.settings.group_cooldown_seconds:
                self._put(
                    self._cooldowns,
                    ("group", reservation.scope),
                    now + snapshot.settings.group_cooldown_seconds,
                )
            self.record("sent" if success else "send_failed")
        finally:
            self._active.pop(reservation.scope, None)

    def preview(self, snapshot, message, evaluation):
        global_reason = self._global_reason(snapshot, message, self.clock())
        return tuple(
            Trace(c.rule.id, global_reason or self.runtime_reason(rule_id=c.rule.id) or "eligible")
            for c in evaluation.candidates
        )

    def export_persistent(self):
        return copy.deepcopy(self._data)

    def restore_persistent(self, data):
        validate_persistent(data)
        self._data = copy.deepcopy(data)

    def apply_controls(self, data):
        self.restore_persistent(data)

    def change_controls(self, action, rule_id=None):
        if action not in {"on", "off", "pause", "resume"}:
            raise ValueError("未知管理操作")
        if action in {"on", "off"} and not rule_id:
            raise ValueError("需要规则 ID")
        data = self.export_persistent()
        if action in {"pause", "resume"}:
            data["global_paused"] = action == "pause"
        elif action == "off":
            data["global_disabled"] = sorted(set(data["global_disabled"]) | {rule_id})
        else:
            data["global_disabled"] = [x for x in data["global_disabled"] if x != rule_id]
        data["revision"] += 1
        validate_persistent(data)
        self._data = data

    def retain_rules(self, ids):
        disabled = [x for x in self._data["global_disabled"] if x in ids]
        if disabled != self._data["global_disabled"]:
            self._data["global_disabled"] = disabled
            self._data["revision"] += 1
