from astrbot.api.message_components import At, AtAll, Plain

from .models import MessageContext, ScopeKey


def extract_message(event) -> MessageContext:
    components = event.get_messages()
    bot_id = str(event.get_self_id())
    group_id = str(event.get_group_id() or "")
    user_id = str(event.get_sender_id())
    return MessageContext(
        ScopeKey(
            str(event.get_platform_id()),
            bot_id,
            "group" if group_id else "private",
            group_id or user_id,
        ),
        user_id,
        str(event.get_sender_name() or user_id),
        str(event.message_obj.message_id or ""),
        "".join(component.text for component in components if isinstance(component, Plain)),
        any(
            isinstance(component, At)
            and not isinstance(component, AtAll)
            and str(component.qq) == bot_id
            for component in components
        ),
    )
