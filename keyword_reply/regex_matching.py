"""Compilation wrapper for regex with mandatory native match deadlines."""

import regex


def compile_regex(pattern: str, ignore_case: bool = False):
    try:
        return regex.compile(pattern, (regex.I | regex.ASCII) if ignore_case else 0)
    except regex.error as exc:
        raise ValueError(f"正则语法无效：{exc.msg}") from exc
