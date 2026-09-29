from dataclasses import dataclass

from .models import Match, MessageContext, Rule

VARIABLES = frozenset(
    {"关键词", "匹配文本", "消息", "用户ID", "用户名", "群ID", "规则ID", "规则名"}
)


@dataclass(frozen=True)
class ReplyTemplates:
    rule_id: str
    rule_name: str
    tokens: tuple[tuple[tuple[bool, str], ...], ...]


def compile_replies(rule: Rule, capture_names: frozenset[str]) -> ReplyTemplates:
    compiled = []
    for text in rule.replies:
        tokens, literal, pos = [], "", 0
        while pos < len(text):
            if text.startswith("{{", pos) or text.startswith("}}", pos):
                literal += text[pos]
                pos += 2
            elif text[pos] == "{":
                end = text.find("}", pos + 1)
                if end < 0:
                    raise ValueError("回复模板花括号不闭合")
                name = text[pos + 1 : end]
                if name not in VARIABLES and not (
                    name.startswith("捕获.") and name[3:] in capture_names
                ):
                    raise ValueError(f"无效回复变量：{name}")
                if literal:
                    tokens.append((False, literal))
                    literal = ""
                tokens.append((True, name))
                pos = end + 1
            elif text[pos] == "}":
                raise ValueError("字面大括号使用 {{ 和 }}")
            else:
                literal += text[pos]
                pos += 1
        if literal:
            tokens.append((False, literal))
        compiled.append(tuple(tokens))
    return ReplyTemplates(rule.id, rule.name, tuple(compiled))


def render_all(
    templates: ReplyTemplates, match: Match, message: MessageContext, *, max_chars: int
) -> tuple[str, ...]:
    values = {
        "关键词": match.keyword,
        "匹配文本": match.text,
        "消息": message.text,
        "用户ID": message.user_id,
        "用户名": message.user_name or message.user_id,
        "群ID": message.scope.target_id if message.scope.chat_type == "group" else "",
        "规则ID": templates.rule_id,
        "规则名": templates.rule_name,
    }
    values.update({f"捕获.{k}": v for k, v in match.groups.items()})
    rendered = tuple(
        "".join(values.get(text, "") if variable else text for variable, text in tokens)
        for tokens in templates.tokens
    )
    return tuple(text for text in rendered if text.strip() and len(text) <= max_chars)
