"""Generate the two small native AstrBot rule forms."""

import json
from dataclasses import asdict
from pathlib import Path

from keyword_reply.config import RETIRED_GLOBAL_FIELDS, RETIRED_SENTINEL
from keyword_reply.models import Rule

LABELS = {
    "id": "规则ID",
    "name": "名称",
    "enabled": "启用",
    "keywords": "关键词",
    "pattern": "句式",
    "capture_mode": "捕获内容",
    "replies": "回复",
    "allowed_group_ids": "适用群",
    "require_at": "需要@机器人",
    "match_type": "规则类型",
}
HINTS = {
    "id": "例如 echo、goodnight；英文、数字、下划线或短横线，不能重复。用于聊天指令。",
    "keywords": "每项一个词，命中任意一个即可。",
    "pattern": "例如：我{关键词}什么。整条消息匹配，首尾空白自动去掉。",
    "capture_mode": "any：任意内容；keywords：仅限关键词列表。",
    "replies": "一项就是一条回复，多项时随机选一条。支持 {关键词}、{用户名} 等文字变量。",
    "allowed_group_ids": "每项一个群号；留空适用全部群。",
    "require_at": "开启后必须直接@机器人；引用和@全体不算。",
}


def rule_items(mode):
    defaults = asdict(
        Rule(
            "",
            "",
            (),
            enabled=False,
            match_type=mode,
            pattern="我{关键词}什么" if mode == "template" else "",
        )
    )
    keys = (
        [
            "id",
            "name",
            "enabled",
            "keywords",
            "replies",
            "allowed_group_ids",
            "require_at",
            "match_type",
        ]
        if mode == "contains"
        else [
            "id",
            "name",
            "enabled",
            "pattern",
            "capture_mode",
            "keywords",
            "replies",
            "allowed_group_ids",
            "require_at",
            "match_type",
        ]
    )
    result = {}
    for key in keys:
        value = defaults[key]
        result[key] = {
            "type": "bool"
            if type(value) is bool
            else "list"
            if isinstance(value, tuple)
            else "text"
            if key == "pattern"
            else "string",
            "description": LABELS[key],
            "default": list(value) if isinstance(value, tuple) else value,
        }
        if key in HINTS:
            result[key]["hint"] = HINTS[key]
        if key == "match_type":
            result[key]["invisible"] = True
        if key == "capture_mode":
            result[key]["options"] = ["any", "keywords"]
        if mode == "template" and key == "keywords":
            result[key]["condition"] = {"capture_mode": "keywords"}
    return result


def main():
    schema = {
        "enabled": {"type": "bool", "description": "启用插件", "default": True},
        "group_cooldown_seconds": {
            "type": "float",
            "description": "群聊回复间隔（秒）",
            "hint": "默认3秒，0表示不限。仅成功回复后开始计时。",
            "default": 3.0,
        },
        "rules": {
            "type": "template_list",
            "description": "回复规则",
            "hint": "新增关键词或句式规则。按列表顺序，第一条命中后只回复一次。填完再启用。",
            "default": [],
            "templates": {
                "keyword": {
                    "name": "关键词回复",
                    "display_item": "name",
                    "hint": "消息包含关键词时回复。",
                    "items": rule_items("contains"),
                },
                "template": {
                    "name": "句式接话",
                    "display_item": "name",
                    "hint": "例如：我吃什么 → 是啊吃什么。",
                    "items": rule_items("template"),
                },
            },
        },
    }
    # Invisible retirement markers survive native normalization and dashboard saves.
    # These are not supported settings and never affect matching.
    for key in sorted(RETIRED_GLOBAL_FIELDS):
        schema[key] = {
            "type": "string",
            "description": "旧版升级检查",
            "default": RETIRED_SENTINEL,
            "invisible": True,
        }
    Path("_conf_schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
