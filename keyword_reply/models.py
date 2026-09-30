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
    order: int = 0
    match_type: str = "contains"
    keywords: tuple[str, ...] = ()
    pattern: str = ""
    capture_mode: str = "any"
    require_at: bool = False
    allowed_group_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginConfig:
    enabled: bool = True
    group_cooldown_seconds: float = 3.0


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
