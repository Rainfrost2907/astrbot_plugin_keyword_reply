"""Strict configuration normalization; never coerce IDs or booleans."""

import math
import re
from dataclasses import MISSING, fields

from .models import ConfigError, ConfigIssue, LoadedConfig, PluginConfig, Rule

ENUMS = {
    "selection_mode": {"priority", "random", "all"},
    "match_type": {"exact", "contains", "prefix", "suffix", "template", "regex"},
    "match_scope": {"full", "search"},
    "capture_mode": {"any", "keywords"},
    "chat_types": {"group", "private", "both"},
    "reply_mode": {"first", "random", "round_robin"},
}
RANGES = {
    "priority": (-10000, 10000),
    "capture_min": (1, 1024),
    "capture_max": (1, 1024),
    "probability": (0, 1),
    "max_replies": (1, 10),
    "dedup_ttl_seconds": (10, 600),
    "max_input_chars": (128, 16384),
    "max_reply_chars": (1, 4000),
    "regex_timeout_ms": (1, 50),
    "evaluation_budget_ms": (20, 500),
    "max_rules": (500, 500),
}


def _issue(rule_id, path, message):
    return ConfigIssue(rule_id, path, "invalid_config", message)


def _parse(cls, raw, prefix, rule_id=None):
    issues, values = [], {}
    known = {f.name for f in fields(cls)} - {"order"}
    for key in raw.keys() - known - {"__template_key"}:
        issues.append(_issue(rule_id, prefix + str(key), "未知配置字段"))
    for field in fields(cls):
        key = field.name
        if key == "order":
            continue
        path = prefix + key
        value = raw.get(key, field.default)
        if value is MISSING:
            issues.append(_issue(rule_id, path, "必填字段"))
            continue
        expected = field.type
        if expected == "bool":
            valid = type(value) is bool
        elif expected == "int":
            valid = type(value) is int
        elif expected == "float":
            valid = type(value) in (int, float) and math.isfinite(value)
            if valid:
                value = float(value)
        elif expected == "str":
            valid = isinstance(value, str)
        else:
            valid = isinstance(value, (list, tuple)) and all(isinstance(x, str) for x in value)
            if valid:
                value = tuple(value)
        if not valid:
            issues.append(_issue(rule_id, path, "字段类型不正确"))
            continue
        values[key] = value
        if key in ENUMS and value not in ENUMS[key]:
            issues.append(_issue(rule_id, path, "无效选项"))
        bound = (0, 3600) if key.endswith("cooldown_seconds") else RANGES.get(key)
        if bound and not bound[0] <= value <= bound[1]:
            issues.append(_issue(rule_id, path, f"必须在 {bound[0]}～{bound[1]} 之间"))
        if isinstance(value, tuple):
            count = (
                50
                if key == "replies"
                else (200 if key in {"keywords", "exclude_keywords"} else 10000)
            )
            length = 2000 if key == "replies" else 256
            if len(value) > count or any(not x.strip() or len(x) > length for x in value):
                issues.append(
                    _issue(
                        rule_id,
                        path,
                        f"列表最多 {count} 项，每项须为非空文字且不超过 {length} 字符",
                    )
                )
    if cls is Rule:
        if "id" in values and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", values["id"]):
            issues.append(
                _issue(rule_id, prefix + "id", "ID 须为 1～64 位字母、数字、下划线或短横线")
            )
        if "name" in values and (not values["name"].strip() or len(values["name"]) > 256):
            issues.append(_issue(rule_id, prefix + "name", "名称不能为空且不超过 256 字符"))
        if not values.get("replies"):
            issues.append(_issue(rule_id, prefix + "replies", "至少配置一条回复"))
        mode = values.get("match_type")
        if mode in {"exact", "contains", "prefix", "suffix"} or (
            mode == "template" and values.get("capture_mode") == "keywords"
        ):
            if not values.get("keywords"):
                issues.append(_issue(rule_id, prefix + "keywords", "该模式要求非空词表"))
        pattern = values.get("pattern", "")
        if len(pattern) > 1024 or (mode in {"template", "regex"} and not pattern):
            issues.append(_issue(rule_id, prefix + "pattern", "模式长度须为 1～1024"))
        if values.get("capture_min", 1) > values.get("capture_max", 128):
            issues.append(_issue(rule_id, prefix + "capture_max", "最大捕获长度不能小于最小长度"))
    return values, issues


def load_config(raw: dict) -> LoadedConfig:
    if not isinstance(raw, dict):
        raise ConfigError((_issue(None, "$", "配置必须是对象"),))
    settings_raw = {k: v for k, v in raw.items() if k != "rules"}
    values, issues = _parse(PluginConfig, settings_raw, "")
    raw_rules = raw.get("rules", [])
    if not isinstance(raw_rules, list) or len(raw_rules) > 500:
        issues.append(_issue(None, "rules", "规则必须为列表且不超过 500 条"))
    else:
        ids = [
            r.get("id")
            for r in raw_rules
            if isinstance(r, dict) and isinstance(r.get("id"), str) and r["id"]
        ]
        if len(ids) != len(set(ids)):
            issues.append(_issue(None, "rules", "规则 ID 重复"))
    if issues:
        raise ConfigError(tuple(issues))
    rules = []
    for order, entry in enumerate(raw_rules):
        prefix = f"rules[{order}]."
        if not isinstance(entry, dict):
            issues.append(_issue(None, prefix[:-1], "规则必须是对象"))
            continue
        rule_id = entry.get("id") if isinstance(entry.get("id"), str) else None
        normalized, local = _parse(Rule, entry, prefix, rule_id)
        issues.extend(local)
        if not local:
            rules.append(Rule(**normalized, order=order))
    return LoadedConfig(PluginConfig(**values), tuple(rules), tuple(issues))
