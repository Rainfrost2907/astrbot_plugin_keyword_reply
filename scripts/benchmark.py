"""Measure bounded evaluation locally, excluding network send time."""

import asyncio
import json
import platform
import statistics
import time
from dataclasses import replace
from pathlib import Path

from keyword_reply.engine import compile_snapshot, evaluate
from keyword_reply.models import MessageContext, ScopeKey
from keyword_reply.policy import RuntimePolicy
from keyword_reply.service import ReplyService
from keyword_reply.storage import StateStore


def measure(snapshot, message, count=1000):
    for _ in range(30):
        evaluate(snapshot, message)
    values = []
    for _ in range(count):
        start = time.perf_counter()
        evaluate(snapshot, message)
        values.append((time.perf_counter() - start) * 1000)
    values.sort()
    return {
        "evaluations": count,
        "median_ms": round(statistics.median(values), 3),
        "p95_ms": round(values[int(count * 0.95) - 1], 3),
    }


async def main():
    message = MessageContext(
        ScopeKey("benchmark", "9000", "group", "1000"), "2000", "tester", "m1", "x" * 4096
    )
    rules = [
        {"id": f"r{i}", "name": str(i), "keywords": [f"keyword{i}"], "replies": ["reply"]}
        for i in range(500)
    ]
    ordinary = compile_snapshot({"rules": rules}, "bench")
    mixed_rules = rules[:400] + [
        dict(r, match_type="regex", pattern="keyword[0-9]+") for r in rules[400:]
    ]
    mixed = compile_snapshot({"rules": mixed_rules}, "mixed")
    timeout = compile_snapshot(
        {
            "rules": [
                {
                    "id": "slow",
                    "name": "timeout",
                    "match_type": "regex",
                    "pattern": "(x+)+$",
                    "replies": ["reply"],
                }
            ]
        },
        "slow",
    )
    service = ReplyService(
        ordinary, RuntimePolicy(), StateStore(Path(".test_runs/benchmark/state.json"))
    )
    counts = await asyncio.gather(
        *(
            service.handle(replace(message, message_id=str(i)), lambda _: asyncio.sleep(0))
            for i in range(100)
        )
    )
    report = {
        "python": platform.python_version(),
        "system": platform.platform(),
        "processor": platform.processor(),
        "ordinary_500_rules_4096_chars": measure(ordinary, message),
        "mixed_400_literal_100_regex": measure(mixed, message),
        "timeout_pattern": measure(timeout, replace(message, text="x" * 4095 + "!"), 100),
        "concurrent_100": {
            reason: sum(r.reason == reason for r in counts) for reason in {r.reason for r in counts}
        },
        "remaining_permits": service._permits.qsize(),
    }
    Path(".test_runs/benchmark.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
