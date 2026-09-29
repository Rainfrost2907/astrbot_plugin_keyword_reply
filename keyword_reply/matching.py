from dataclasses import dataclass
from string import ascii_lowercase, ascii_uppercase

import regex

from .models import Match, Rule
from .regex_matching import compile_regex

ASCII_FOLD = str.maketrans(ascii_uppercase, ascii_lowercase)


def fold(text: str, ignore_case: bool) -> str:
    return text.translate(ASCII_FOLD) if ignore_case else text


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
    capture_names: frozenset[str]

    def search(self, raw_text: str, *, timeout_s: float) -> Match | None:
        rule = self.rule
        original = raw_text.strip() if rule.trim else raw_text
        if rule.ignore_trailing_question_marks:
            original = original.rstrip("?？")
        if not original:
            return None
        text = fold(original, rule.ignore_case) if rule.match_type != "regex" else original
        if self.pattern is not None:
            operation = (
                self.pattern.fullmatch if rule.match_scope == "full" else self.pattern.search
            )
            found = operation(text, timeout=timeout_s)
            if found is None:
                return None
            start, end = found.span()
            if start == end:
                return None
            matched = original[start:end]
            if rule.match_type == "template":
                a, b = found.span("kw")
                keyword = original[a:b]
                if not keyword.strip() or not rule.capture_min <= len(keyword) <= rule.capture_max:
                    return None
                return Match(keyword, matched, {})
            groups = {str(i): found.group(i) or "" for i in range(1, self.pattern.groups + 1)}
            groups.update({k: v or "" for k, v in found.groupdict().items()})
            return Match(matched, matched, groups)
        hits = []
        for order, keyword in enumerate(rule.keywords):
            word = fold(keyword, rule.ignore_case)
            position = text.find(word)
            if rule.match_type == "exact" and text != word:
                continue
            if rule.match_type == "prefix" and not text.startswith(word):
                continue
            if rule.match_type == "suffix":
                if not text.endswith(word):
                    continue
                position = len(text) - len(word)
            if position >= 0:
                hits.append((position, -len(word), order, len(word)))
        if not hits:
            return None
        position, _, _, length = min(hits)
        keyword = original[position : position + length]
        return Match(keyword, keyword, {})


def compile_matcher(rule: Rule) -> CompiledMatcher:
    if rule.match_type == "regex":
        pattern = compile_regex(rule.pattern, rule.ignore_case)
        names = frozenset(str(i) for i in range(1, pattern.groups + 1)) | frozenset(
            pattern.groupindex
        )
        return CompiledMatcher(rule, pattern, names)
    if rule.match_type == "template":
        prefix, suffix = template_parts(rule.pattern)
        if rule.capture_mode == "keywords":
            words = sorted(rule.keywords, key=len, reverse=True)
            slot = "|".join(
                regex.escape(fold(w, rule.ignore_case))
                for w in words
                if "\n" not in w
                and "\r" not in w
                and rule.capture_min <= len(w) <= rule.capture_max
            )
            if not slot:
                raise ValueError("词表没有符合捕获长度与单行限制的词")
            slot = f"(?P<kw>{slot})"
        else:
            slot = rf"(?P<kw>[^\r\n]{{{rule.capture_min},{rule.capture_max}}}?)"
        pattern = (
            regex.escape(fold(prefix, rule.ignore_case))
            + slot
            + regex.escape(fold(suffix, rule.ignore_case))
        )
        return CompiledMatcher(rule, compile_regex(pattern), frozenset())
    return CompiledMatcher(rule, None, frozenset())
