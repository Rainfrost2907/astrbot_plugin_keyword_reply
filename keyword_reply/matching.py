"""Literal keyword matching and bounded, full-message sentence capture."""

from dataclasses import dataclass

import regex

from .models import Match, Rule


def template_parts(pattern: str) -> tuple[str, str]:
    pieces = [""]
    index = 0
    while index < len(pattern):
        if pattern.startswith("{{", index) or pattern.startswith("}}", index):
            pieces[-1] += pattern[index]
            index += 2
        elif pattern.startswith("{关键词}", index):
            pieces.append("")
            index += len("{关键词}")
        elif pattern[index] in "{}":
            raise ValueError("句式仅允许一个 {关键词}，字面大括号使用 {{ 和 }}")
        else:
            pieces[-1] += pattern[index]
            index += 1
    if len(pieces) != 2:
        raise ValueError("句式必须且只能包含一个 {关键词}")
    return pieces[0], pieces[1]


@dataclass(frozen=True)
class CompiledMatcher:
    rule: Rule
    pattern: object | None
    capture_names: frozenset[str] = frozenset()

    def search(self, raw_text: str, *, timeout_s: float) -> Match | None:
        text = raw_text.strip()
        if not text:
            return None
        if self.pattern is not None:
            found = self.pattern.fullmatch(text, timeout=timeout_s)
            if found is None or not found["kw"].strip():
                return None
            return Match(found["kw"], text, {})
        hits = []
        for order, keyword in enumerate(self.rule.keywords):
            position = text.find(keyword)
            if position >= 0:
                hits.append((position, -len(keyword), order, keyword))
        if not hits:
            return None
        keyword = min(hits)[-1]
        return Match(keyword, keyword, {})


def compile_matcher(rule: Rule) -> CompiledMatcher:
    if rule.match_type == "template":
        prefix, suffix = template_parts(rule.pattern)
        if rule.capture_mode == "keywords":
            words = sorted(rule.keywords, key=len, reverse=True)
            slot = "|".join(
                regex.escape(w)
                for w in words
                if "\n" not in w and "\r" not in w and 1 <= len(w) <= 128
            )
            if not slot:
                raise ValueError("限定词表须含1～128字符的单行词")
        else:
            slot = r"[^\r\n]{1,128}?"
        expression = regex.escape(prefix) + f"(?P<kw>{slot})" + regex.escape(suffix)
        return CompiledMatcher(rule, regex.compile(expression))
    return CompiledMatcher(rule, None)
