from .models import MessageContext, Rule


def scope_reason(rule: Rule, message: MessageContext) -> str | None:
    if not rule.enabled:
        return "disabled"
    if message.scope.chat_type != "group":
        return "wrong_chat_type"
    if rule.allowed_group_ids and message.scope.target_id not in rule.allowed_group_ids:
        return "scope_denied"
    if rule.require_at and not message.mentioned_bot:
        return "needs_at"
    return None
