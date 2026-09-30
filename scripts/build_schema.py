"""Regenerate the native AstrBot form from the plugin model defaults."""

import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from keyword_reply.config import ENUMS
from keyword_reply.models import PluginConfig, Rule

LABELS = {
    "enabled": "基本：启用",
    "allow_private": "基本：允许私聊",
    "selection_mode": "回复：多规则选择方式",
    "max_replies": "回复：多条模式上限",
    "group_cooldown_seconds": "限制：会话总冷却秒数",
    "dedup_ttl_seconds": "限制：消息ID去重秒数",
    "max_input_chars": "限制：最大输入字符",
    "max_reply_chars": "限制：最大回复字符",
    "regex_timeout_ms": "限制：单次正则超时毫秒",
    "evaluation_budget_ms": "限制：总评估预算毫秒",
    "max_rules": "限制：规则数量上限",
    "ignore_command_prefixes": "范围：忽略的命令前缀",
    "blocked_user_ids": "范围：用户黑名单",
    "platform_ids": "范围：平台实例ID",
    "id": "基本：唯一规则ID",
    "name": "基本：规则名称",
    "priority": "基本：优先级",
    "match_type": "匹配：匹配方式",
    "keywords": "匹配：关键词列表",
    "pattern": "匹配：句式或正则",
    "match_scope": "匹配：全句或搜索",
    "capture_mode": "匹配：捕获模式",
    "capture_min": "匹配：最少捕获字符",
    "capture_max": "匹配：最多捕获字符",
    "ignore_case": "匹配：忽略ASCII大小写",
    "trim": "匹配：去掉正文首尾空白",
    "ignore_trailing_question_marks": "匹配：忽略末尾问号",
    "exclude_keywords": "匹配：排除词",
    "chat_types": "范围：聊天类型",
    "require_at": "范围：群聊必须直接@机器人",
    "allowed_group_ids": "范围：群白名单",
    "blocked_group_ids": "范围：群黑名单",
    "allowed_user_ids": "范围：用户白名单",
    "reply_mode": "回复：候选选择方式",
    "replies": "回复：文字候选列表",
    "probability": "限制：触发概率",
    "group_rule_cooldown_seconds": "限制：会话内本规则冷却秒数",
    "user_rule_cooldown_seconds": "限制：会话内用户本规则冷却秒数",
}
HINTS = {
    "id": "填写1～64位英文字母、数字、下划线或短横线，全部规则中唯一。修改ID视为新规则。",
    "enabled": "面板关闭优先于聊天命令开启。",
    "selection_mode": "priority：优先级高者一条，同级按列表顺序；random：符合条件的规则均匀选一条；all：按顺序发送，受上限限制。",
    "match_type": "contains包含、exact全句相等、prefix开头、suffix结尾、template句式捕获、regex正则。关键词为OR关系。",
    "keywords": "普通匹配填写一个或多个关键词；句式的keywords捕获模式仅允许这些词。any模式不需要词表。",
    "pattern": "句式示例：我{关键词}什么，恰好一个占位符；正则示例：^我(?P<动作>.+?)什么$。",
    "match_scope": "full：整段正文必须匹配；search：正文任意位置匹配。仅作用于句式和正则。",
    "capture_mode": "any：捕获任意非空、非跨行内容；keywords：仅捕获词表中的内容。",
    "replies": "每项一条候选，可含换行；变量：{关键词}、{匹配文本}、{消息}、{用户名}、{用户ID}、{群ID}、{规则ID}、{规则名}、{捕获.动作}或{捕获.1}。{{和}}表示字面花括号。",
    "reply_mode": "first第一条；random均匀随机一条；round_robin按会话轮询，仅发送成功后推进。",
    "probability": "0～1：0永不触发，1必定参与选择；每个候选规则只抽样一次。test不抽样。",
    "require_at": "仅顶层直接@本机器人满足；引用、@全体成员不算。私聊不要求@。",
    "ignore_case": "普通词/句式仅折叠ASCII英文大小写，保持捕获原文。正则同时开启ASCII标志，\\w、\\d等也使用ASCII语义。",
    "ignore_trailing_question_marks": "去掉正文末尾连续的?和？，然后匹配；其他标点不处理。",
    "exclude_keywords": "任一排除词出现在处理后的正文中即跳过本规则。",
    "regex_timeout_ms": "正则实际执行超时后跳过该规则，避免阻塞消息处理。",
    "evaluation_budget_ms": "总匹配预算耗尽时整条消息不自动回复。",
    "max_rules": "首版固定500，超过500条拒绝整个新配置。",
    "platform_ids": "填写AstrBot平台实例ID，空列表不限。不是适配器名称。",
    "ignore_command_prefixes": "正文去掉左侧空白后，以任一前缀开头即不自动回复。默认忽略/；管理命令仍可用。",
}


def nodes(defaults):
    result = {}
    for key, value in defaults.items():
        if key == "order":
            continue
        kind = (
            "bool"
            if type(value) is bool
            else "int"
            if type(value) is int
            else "float"
            if type(value) is float
            else "list"
            if isinstance(value, tuple | list)
            else "text"
            if key == "pattern"
            else "string"
        )
        node = {
            "type": kind,
            "description": LABELS[key],
            "default": list(value) if isinstance(value, tuple) else value,
        }
        hint = HINTS.get(key, "")
        if key.endswith("_ids") and key != "platform_ids":
            hint = "QQ号/群号填写字符串。空列表表示不限制；黑名单优先于白名单。群限制不作用于私聊。"
        if key.endswith("cooldown_seconds"):
            hint = "0秒表示关闭该冷却。仅成功发送后计时；私聊按独立会话计算。"
        if hint:
            node["hint"] = hint
        if key in ENUMS:
            node["options"] = sorted(ENUMS[key])
        result[key] = node
    return result


def main():
    schema = nodes(asdict(PluginConfig()))
    templates = {}
    for key, label, mode in [
        ("keyword", "关键词", "contains"),
        ("template", "句式", "template"),
        ("regex", "正则", "regex"),
    ]:
        defaults = asdict(Rule("", "", ()))
        defaults.update(
            match_type=mode, enabled=False, pattern="我{关键词}什么" if mode == "template" else ""
        )
        templates[key] = {
            "name": label,
            "display_item": "name",
            "hint": "填写唯一ID、名称及回复候选后启用；高级选项可保留默认。",
            "items": deepcopy(nodes(defaults)),
        }
    schema["rules"] = {
        "type": "template_list",
        "description": "回复规则",
        "hint": "最多500条。新增默认禁用，填完再开启；同级按列表顺序。",
        "default": [],
        "templates": templates,
    }
    Path("_conf_schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
