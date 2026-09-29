import time

from .config import load_config
from .matching import compile_matcher, fold
from .models import (
    Candidate,
    CompiledRule,
    ConfigIssue,
    Evaluation,
    MessageContext,
    Snapshot,
    Trace,
)
from .rendering import compile_replies, render_all
from .scope import scope_reason


def compile_snapshot(raw: dict, revision: str) -> Snapshot:
    config = load_config(raw)
    compiled, issues = [], list(config.issues)
    for rule in config.rules:
        path = f"rules[{rule.order}].pattern"
        try:
            matcher = compile_matcher(rule)
            path = f"rules[{rule.order}].replies"
            replies = compile_replies(rule, matcher.capture_names)
            compiled.append(CompiledRule(rule, matcher, replies))
        except ValueError as exc:
            issues.append(ConfigIssue(rule.id, path, "invalid_rule", str(exc)))
    compiled.sort(key=lambda item: (-item.rule.priority, item.rule.order))
    return Snapshot(revision, config.settings, tuple(compiled), tuple(issues))


def evaluate(snapshot: Snapshot, message: MessageContext, *, clock=time.monotonic) -> Evaluation:
    settings = snapshot.settings
    reason = None
    if not settings.enabled:
        reason = "disabled"
    elif message.scope.chat_type == "private" and not settings.allow_private:
        reason = "wrong_chat_type"
    elif settings.platform_ids and message.scope.platform_id not in settings.platform_ids:
        reason = "wrong_platform"
    elif message.user_id in settings.blocked_user_ids:
        reason = "scope_denied"
    elif len(message.text) > settings.max_input_chars:
        reason = "input_too_long"
    elif not message.text.strip():
        reason = "no_match"
    if reason:
        return Evaluation((), (Trace("*", reason),))
    started = clock()
    deadline = started + settings.evaluation_budget_ms / 1000
    candidates, traces = [], []
    for item in snapshot.rules:
        remaining = deadline - clock()
        if remaining <= 0:
            return Evaluation((), (*traces, Trace("*", "budget_exhausted")), True)
        rule = item.rule
        reason = scope_reason(rule, message)
        if not reason and any(
            fold(word, rule.ignore_case) in fold(message.text, rule.ignore_case)
            for word in rule.exclude_keywords
        ):
            reason = "excluded"
        if reason:
            traces.append(Trace(rule.id, reason))
            continue
        try:
            found = item.matcher.search(
                message.text, timeout_s=min(settings.regex_timeout_ms / 1000, remaining)
            )
        except TimeoutError:
            traces.append(Trace(rule.id, "regex_timeout"))
            continue
        if not found:
            traces.append(Trace(rule.id, "no_match"))
            continue
        replies = render_all(item.replies, found, message, max_chars=settings.max_reply_chars)
        if not replies:
            traces.append(Trace(rule.id, "empty_reply", "候选渲染后为空或超过长度限制"))
            continue
        candidates.append(Candidate(rule, found, replies))
        traces.append(Trace(rule.id, "matched"))
    if clock() >= deadline:
        return Evaluation((), (*traces, Trace("*", "budget_exhausted")), True)
    return Evaluation(tuple(candidates), tuple(traces))
