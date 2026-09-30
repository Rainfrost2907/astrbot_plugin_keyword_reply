import re
from dataclasses import dataclass, replace

from .scope import scope_reason
from .service import REASONS
from .version import __version__

HELP = """关键词回复管理（仅 AstrBot 机器人管理员）
/kwr list [页码]：查看本群规则，每页10条
/kwr on|off <ID>：开启/关闭规则（全部群）
/kwr pause|resume：暂停/恢复插件（全部群）
/kwr test|testat <ID|all> <正文>：只读测试，testat模拟@机器人
/kwr validate|reload|status：检查配置、重新读取、查看状态
面板关闭的规则不能通过 on 开启。也可使用 /关键词回复。
唤醒前缀以 AstrBot 配置为准。"""


@dataclass(frozen=True)
class ParsedCommand:
    action: str = "help"
    rule_id: str | None = None
    text: str = ""
    page: int = 1


def parse_command(text: str) -> ParsedCommand | None:
    match = re.match(r"^\s*(?:kwr|关键词回复)(?:\s+|$)", text)
    if not match:
        return None
    parts = text[match.end() :].split(maxsplit=1)
    if not parts:
        return ParsedCommand()
    action = parts[0]
    rest = parts[1] if len(parts) > 1 else ""
    if action in {"test", "testat"}:
        body = re.match(r"^(\S+)\s(.*)$", rest, re.DOTALL)
        if not body or not body[2].strip():
            raise ValueError("用法：kwr test|testat <规则ID|all> <正文>")
        return ParsedCommand(action, None if body[1] == "all" else body[1], text=body[2])
    args = rest.split()
    if action in {"help", "validate", "reload", "status", "pause", "resume"} and not args:
        return ParsedCommand(action)
    if action == "list" and len(args) <= 1:
        if args and (
            not args[0].isascii() or not args[0].isdigit() or len(args[0]) > 8 or int(args[0]) < 1
        ):
            raise ValueError("页码必须为正整数")
        return ParsedCommand(action, page=int(args[0]) if args else 1)
    if action in {"on", "off"} and len(args) == 1:
        return ParsedCommand(action, args[0])
    raise ValueError("未知操作或参数错误。发送 kwr help 查看用法。")


def limit_report(text: str) -> str:
    return text if len(text) <= 4000 else text[:3920] + "\n…内容较长，请指定规则ID或下一页。"


async def execute_command(service, command, context, is_admin: bool) -> str:
    if not is_admin:
        return "仅 AstrBot 配置中的机器人管理员可以使用关键词回复管理命令。"
    try:
        return limit_report(await _execute(service, command, context))
    except (ValueError, OSError) as exc:
        return limit_report(
            "操作未完成："
            + (str(exc) if isinstance(exc, ValueError) else "文件读写失败，管理状态未提交。")
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
        lines = [f"本群规则：{len(rules)} 条，第 {command.page} 页"]
        for rule in rules[start : start + 10]:
            reason = scope_reason(rule, context) or service.policy.runtime_reason(rule_id=rule.id)
            lines.append(
                f"{rule.id}｜{rule.name}｜{REASONS.get(reason, reason) if reason else '可用'}"
            )
        if start + 10 < len(rules):
            lines.append(f"下一页：kwr list {command.page + 1}")
        return "\n".join(lines)
    if action in {"on", "off", "pause", "resume"}:
        await service.update_runtime(action, command.rule_id)
        if command.rule_id and not any(
            c.rule.id == command.rule_id for c in service.snapshot.rules
        ):
            return "配置已变化：规则已删除或无效，已清理其运行开关。"
        return f"已执行 {action}，作用于全部群。面板禁用和适用群限制仍然有效。"
    if action in {"validate", "reload"}:
        if action == "reload":
            await service.reload_config()
        errors = "\n".join(
            f"{i.rule_id or '*'} {i.path}: {i.message}" for i in service.config_issues
        )
        return f"有效规则 {len(service.snapshot.rules)} 条，配置问题 {len(service.config_issues)} 条。\n{errors}\n{service.last_error}"
    if action == "status":
        status = service.status(context)
        return f"插件版本：{__version__}\n面板启用：{status['enabled']}\n运行暂停：{status['runtime_disabled']}\n有效规则：{status['valid_rules']}\n配置问题：{status['issues']}\n最近错误：{status['last_error']}"
    raise ValueError("未知操作")
