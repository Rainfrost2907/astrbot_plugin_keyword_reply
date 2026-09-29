from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .matching import CompiledMatcher
    from .rendering import ReplyTemplates


@dataclass(frozen=True)
class ScopeKey:
    platform_id: str
    bot_id: str
    chat_type: str
    target_id: str


@dataclass(frozen=True)
class MessageContext:
    scope: ScopeKey
    user_id: str
    user_name: str
    message_id: str
    text: str
    mentioned_bot: bool = False


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    replies: tuple[str, ...]
    enabled: bool = True
    priority: int = 0
    order: int = 0
    match_type: str = "contains"
    keywords: tuple[str, ...] = ()
    pattern: str = ""
    match_scope: str = "full"
    capture_mode: str = "any"
    capture_min: int = 1
    capture_max: int = 128
    ignore_case: bool = False
    trim: bool = True
    ignore_trailing_question_marks: bool = False
    exclude_keywords: tuple[str, ...] = ()
    chat_types: str = "group"
    require_at: bool = False
    platform_ids: tuple[str, ...] = ()
    allowed_group_ids: tuple[str, ...] = ()
    blocked_group_ids: tuple[str, ...] = ()
    allowed_user_ids: tuple[str, ...] = ()
    blocked_user_ids: tuple[str, ...] = ()
    reply_mode: str = "random"
    probability: float = 1.0
    group_rule_cooldown_seconds: float = 0.0
    user_rule_cooldown_seconds: float = 10.0


@dataclass(frozen=True)
class PluginConfig:
    enabled: bool = True
    allow_private: bool = False
    selection_mode: str = "priority"
    max_replies: int = 3
    group_cooldown_seconds: float = 3.0
    dedup_ttl_seconds: int = 120
    max_input_chars: int = 4096
    max_reply_chars: int = 2000
    regex_timeout_ms: int = 10
    evaluation_budget_ms: int = 100
    max_rules: int = 500
    ignore_command_prefixes: tuple[str, ...] = ("/",)
    blocked_user_ids: tuple[str, ...] = ()
    platform_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConfigIssue:
    rule_id: str | None
    path: str
    code: str
    message: str


class ConfigError(ValueError):
    def __init__(self, issues: tuple[ConfigIssue, ...]):
        self.issues = issues
        super().__init__("; ".join(f"{i.path}: {i.message}" for i in issues))


@dataclass(frozen=True)
class LoadedConfig:
    settings: PluginConfig
    rules: tuple[Rule, ...]
    issues: tuple[ConfigIssue, ...]


@dataclass(frozen=True)
class Match:
    keyword: str
    text: str
    groups: dict[str, str]


@dataclass(frozen=True)
class Trace:
    rule_id: str
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class Candidate:
    rule: Rule
    match: Match
    replies: tuple[str, ...]


@dataclass(frozen=True)
class Evaluation:
    candidates: tuple[Candidate, ...]
    traces: tuple[Trace, ...]
    exhausted: bool = False


@dataclass(frozen=True)
class CompiledRule:
    rule: Rule
    matcher: CompiledMatcher
    replies: ReplyTemplates


@dataclass(frozen=True)
class Snapshot:
    revision: str
    settings: PluginConfig
    rules: tuple[CompiledRule, ...]
    issues: tuple[ConfigIssue, ...]


@dataclass(frozen=True)
class Delivery:
    rule_id: str
    text: str
    next_cursor: int | None


@dataclass(frozen=True)
class Reservation:
    token: str
    scope: ScopeKey
    user_id: str
    message_id: str
    deliveries: tuple[Delivery, ...]
    revision: str


@dataclass(frozen=True)
class SendOutcome:
    rule_id: str
    attempted: bool
    success: bool
    error_code: str | None = None


@dataclass(frozen=True)
class HandleResult:
    reason: str
    sent_rule_ids: tuple[str, ...] = ()
