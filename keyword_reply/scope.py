from .models import MessageContext, Rule


def scope_reason(rule: Rule, message: MessageContext) -> str | None:
    if not rule.enabled:
        return "disabled"
    if rule.platform_ids and message.scope.platform_id not in rule.platform_ids:
        return "wrong_platform"
    if rule.chat_types not in {"both", message.scope.chat_type}:
        return "wrong_chat_type"
    if message.user_id in rule.blocked_user_ids or (
        rule.allowed_user_ids and message.user_id not in rule.allowed_user_ids
    ):
        return "scope_denied"
    if message.scope.chat_type == "group":
        group = message.scope.target_id
        if group in rule.blocked_group_ids or (
            rule.allowed_group_ids and group not in rule.allowed_group_ids
        ):
            return "scope_denied"
        if rule.require_at and not message.mentioned_bot:
            return "needs_at"
    return None
