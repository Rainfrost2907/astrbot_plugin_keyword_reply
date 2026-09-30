import json
import re
from dataclasses import dataclass, replace

from .scope import scope_reason
from .service import REASONS

HELP = """关键词回复管理（仅 AstrBot 机器人管理员）
/kwr list [页码]：本会话规则，每页10条
/kwr show <ID>：规则详情
/kwr on|off <ID> [here|global]：运行开关
/kwr pause|resume|reset [here|global]：暂停、恢复、清除该层管理覆盖
/kwr test|testat <ID|all> <正文>：只读诊断，testat模拟直接@机器人
/kwr validate|reload|status|stats
默认 here 为当前会话；global 影响全部会话。
reset 不清冷却/去重/轮询；on 不越过面板禁用。
也可使用 /关键词回复。唤醒前缀以 AstrBot 配置为准。"""


@dataclass(frozen=True)
class ParsedCommand:
    action: str = "help"
    rule_id: str | None = None
    scope: str = "here"
    text: str = ""
    page: int = 1


def parse_command(text: str) -> ParsedCommand | None:
    match = re.match(r"^\s*(?:kwr|关键词回复)(?:\s+|$)", text)
    if not match:
        return None
    tail = text[match.end() :]
    if not tail:
        return ParsedCommand()
    parts = tail.split(maxsplit=1)
    action = parts[0]
    rest = parts[1] if len(parts) > 1 else ""
    if action in {"test", "testat"}:
        body = re.match(r"^(\S+)\s(.*)$", rest, re.DOTALL)
        if not body or not body[2].strip():
            raise ValueError("用法：kwr test|testat <规则ID|all> <正文>")
        return ParsedCommand(action, None if body[1] == "all" else body[1], text=body[2])
    args = rest.split()
    if action in {"help", "validate", "reload", "status", "stats"} and not args:
        return ParsedCommand(action)
    if action == "list" and len(args) <= 1:
        if args and (
            not args[0].isascii() or not args[0].isdigit() or len(args[0]) > 8 or int(args[0]) < 1
        ):
            raise ValueError("页码必须为正整数")
        return ParsedCommand(action, page=int(args[0]) if args else 1)
    if action == "show" and len(args) == 1:
        return ParsedCommand(action, args[0])
    if action in {"on", "off"} and len(args) in {1, 2}:
        scope = args[1] if len(args) == 2 else "here"
        if scope in {"here", "global"}:
            return ParsedCommand(action, args[0], scope)
    if action in {"pause", "resume", "reset"} and len(args) <= 1:
        scope = args[0] if args else "here"
        if scope in {"here", "global"}:
            return ParsedCommand(action, scope=scope)
    raise ValueError("未知操作或参数错误。发送 kwr help 查看用法。")


def limit_report(text: str) -> str:
    if len(text) <= 4000:
        return text
    omitted = len(text) - 3920
    return (
        text[:3920]
        + f"\n…省略 {omitted} 字符，请用 show <ID>、test <ID> 或 list <下一页> 缩小范围。"
    )


async def execute_command(service, command, context, is_admin: bool) -> str:
    if not is_admin:
        return "仅 AstrBot 配置中的机器人管理员可以使用关键词回复管理命令。"
    try:
        return limit_report(await _execute(service, command, context))
    except (ValueError, OSError) as exc:
        return limit_report(
            "操作未完成："
            + (
                str(exc)
                if isinstance(exc, ValueError)
                else "文件读写失败，管理状态未提交，请查看后台。"
            )
        )


async def _execute(service, command, context):
    action = command.action
    if action == "help":
        return HELP
    if action in {"test", "testat"}:
        return await service.diagnose(
            replace(context, text=command.text, mentioned_bot=action == "testat"), command.rule_id
        )
    if action == "list":
        rules = [
            c.rule
            for c in service.snapshot.rules
            if scope_reason(replace(c.rule, enabled=True, require_at=False), context) is None
        ]
        start = (command.page - 1) * 10
        lines = [f"本会话规则：{len(rules)} 条，第 {command.page} 页"]
        for rule in rules[start : start + 10]:
            reason = scope_reason(rule, context) or service.policy.runtime_reason(
                context.scope, rule.id
            )
            lines.append(
                f"{rule.id}｜{rule.name}｜优先级{rule.priority}｜{REASONS.get(reason, reason) if reason else '可用'}"
            )
        if start + 10 < len(rules):
            lines.append(f"省略 {len(rules) - start - 10} 条，下一页：kwr list {command.page + 1}")
        return "\n".join(lines)
    if action == "show":
        from dataclasses import asdict

        rule = next((c.rule for c in service.snapshot.rules if c.rule.id == command.rule_id), None)
        if not rule:
            raise ValueError("规则不存在或配置无效")
        reason = scope_reason(rule, context) or service.policy.runtime_reason(
            context.scope, rule.id
        )
        return f"当前限制：{REASONS.get(reason, reason) if reason else '无'}\n" + json.dumps(
            asdict(rule), ensure_ascii=False, indent=2
        )
    if action in {"on", "off", "pause", "resume", "reset"}:
        await service.update_runtime(
            action, command.rule_id, context.scope, command.scope == "global"
        )
        remaining = service.policy.runtime_reason(context.scope, command.rule_id)
        if not service.snapshot.settings.enabled:
            remaining = "disabled"
        if command.rule_id:
            rule = next(c.rule for c in service.snapshot.rules if c.rule.id == command.rule_id)
            remaining = scope_reason(rule, context) or remaining
        return f"已执行 {action}（{command.scope}）。剩余限制：{REASONS.get(remaining, remaining) if remaining else '无'}。"
    if action in {"validate", "reload"}:
        if action == "reload":
            await service.reload_config()
        errors = "\n".join(
            f"{i.rule_id or '*'} {i.path}: {i.message}" for i in service.config_issues
        )
        return f"有效规则 {len(service.snapshot.rules)} 条，配置问题 {len(service.config_issues)} 条。\n{errors}\n{service.last_error}"
    if action == "status":
        labels = {
            "revision": "配置版本",
            "scope": "当前会话",
            "enabled": "面板总开关",
            "runtime_disabled": "运行暂停",
            "valid_rules": "有效规则",
            "issues": "配置问题",
            "inflight": "在途发送",
            "dedup_entries": "去重项",
            "cooldown_entries": "冷却项",
            "last_error": "最近错误",
        }
        return "\n".join(f"{labels[k]}：{v}" for k, v in service.status(context).items())
    if action == "stats":
        return "本次加载以来统计（重载后清零）：\n" + "\n".join(
            f"{REASONS.get(k, k)}：{v}" for k, v in service.policy.stats.items()
        )
    raise ValueError("未知操作")
