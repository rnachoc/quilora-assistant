"""Deterministic graders: each expectation becomes a named pass/fail check."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from quilora.agent.loop import TurnResult, guess_language
from quilora.evals.cases import Expect


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class CaseRun:
    """What happened when a case was played: one TurnResult per customer message."""

    turns: list[TurnResult]
    returns_created: int = 0
    tickets_created: int = 0
    judge: Check | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def norm(text: str) -> str:
    return strip_accents(text).lower()


def _match_value(actual: Any, matcher: Any) -> bool:
    if isinstance(matcher, dict):
        ok = True
        if "lte" in matcher:
            ok &= actual is not None and float(actual) <= float(matcher["lte"])
        if "gte" in matcher:
            ok &= actual is not None and float(actual) >= float(matcher["gte"])
        if "contains" in matcher:
            ok &= actual is not None and norm(str(matcher["contains"])) in norm(str(actual))
        if "in" in matcher:
            ok &= actual in matcher["in"]
        if "present" in matcher:
            ok &= (actual is not None) == bool(matcher["present"])
        return bool(ok)
    if isinstance(actual, str) and isinstance(matcher, str):
        return norm(actual) == norm(matcher)
    return actual == matcher


def grade(expect: Expect, turns: list[TurnResult], run: CaseRun, *, scope: str) -> list[Check]:
    """Grade `expect` against `turns` (the last one provides the reply)."""
    checks: list[Check] = []
    reply = turns[-1].reply if turns else ""
    reply_n = norm(reply)
    calls = [c for t in turns for c in t.tool_calls]
    called = [c.name for c in calls]
    p = f"{scope}:"

    for tool in expect.tools_called:
        checks.append(Check(f"{p}called:{tool}", tool in called, f"called={called}"))
    for tool in expect.tools_not_called:
        checks.append(Check(f"{p}not_called:{tool}", tool not in called, f"called={called}"))
    if expect.no_tools is not None:
        checks.append(Check(f"{p}no_tools", (not called) == expect.no_tools, f"called={called}"))

    for tool, fields in expect.tool_args.items():
        candidates = [c.input for c in calls if c.name == tool]
        ok = any(all(_match_value(args.get(k), m) for k, m in fields.items())
                 for args in candidates)
        checks.append(Check(f"{p}args:{tool}", ok, f"inputs={candidates}"))

    codes = [c.error_code for c in calls if c.error_code]
    for code in expect.error_codes_include:
        checks.append(Check(f"{p}error_code:{code}", code in codes, f"codes={codes}"))

    for needle in expect.reply_contains_all:
        checks.append(Check(f"{p}contains:{needle}", norm(needle) in reply_n))
    if expect.reply_contains_any:
        ok = any(norm(n) in reply_n for n in expect.reply_contains_any)
        checks.append(Check(f"{p}contains_any", ok, f"any of {expect.reply_contains_any}"))
    for needle in expect.reply_not_contains:
        checks.append(Check(f"{p}not_contains:{needle}", norm(needle) not in reply_n))
    for pattern in expect.reply_matches:
        ok = re.search(strip_accents(pattern), strip_accents(reply), re.IGNORECASE) is not None
        checks.append(Check(f"{p}matches:{pattern}", ok))

    if expect.language:
        detected = guess_language(reply)
        checks.append(Check(f"{p}language:{expect.language}", detected == expect.language,
                            f"detected={detected}"))
    if expect.handoff is not None:
        handed = any(t.handed_off for t in turns)
        checks.append(Check(f"{p}handoff={expect.handoff}", handed == expect.handoff))
    if expect.return_created is not None:
        created = run.returns_created > 0
        checks.append(Check(f"{p}return_created={expect.return_created}",
                            created == expect.return_created, f"returns={run.returns_created}"))

    flags = {f for t in turns for f in t.flags}
    for flag in expect.flags_include:
        checks.append(Check(f"{p}flag:{flag}", flag in flags, f"flags={sorted(flags)}"))
    for flag in expect.flags_exclude:
        checks.append(Check(f"{p}no_flag:{flag}", flag not in flags, f"flags={sorted(flags)}"))
    return checks
