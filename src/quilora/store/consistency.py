"""Check a store's policy texts against its profile (and against themselves).

    python -m quilora.store.consistency [--store-dir DIR] [--strict]

Real shops often publish contradictory numbers: a 30-day return window in one section and
14 days in another, or two different processing times in the same shipping policy. An
assistant that retrieves one section or the other will answer differently each time.
This check finds sentences that state a number of days for a key fact and reports:

  * values that differ from the store profile (the single source of truth), and
  * facts stated with more than one value across the policies.

It is a heuristic meant for a human review before going live, not a legal analysis: a
sentence such as "the legal minimum is 14 days, we offer 30" is reported too, on purpose.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from quilora.search.chunking import PolicyChunk, load_policies
from quilora.store.profile import StoreProfile, load_profile

NUMBER_WORDS = {
    "one": 1, "uno": 1, "un": 1, "two": 2, "dos": 2, "three": 3, "tres": 3, "five": 5,
    "cinco": 5, "seven": 7, "siete": 7, "ten": 10, "diez": 10, "fourteen": 14, "catorce": 14,
    "fifteen": 15, "quince": 15, "twenty": 20, "veinte": 20, "thirty": 30, "treinta": 30,
}
_DAYS = re.compile(r"\b(\d{1,3}|" + "|".join(NUMBER_WORDS) + r")\s+(?:\w+\s+)?"
                   r"(?:days|day|d[ií]as|d[ií]a)\b", re.IGNORECASE)
WINDOW_WORDS = 12  # how far before the number a fact keyword may appear

FACT_KEYWORDS = {
    # "returned" is excluded on purpose: "the amount is returned within 5 days" is about money.
    "return_window_days": r"return(?!ed)|withdraw|devoluci|devolver|desisti|retract",
    "refund_days": r"refund|reembols|reintegr",
    "processing_business_days": r"process|procesa|prepar|handling|dispatch|despach",
}


@dataclass(frozen=True)
class Finding:
    """One sentence stating a number of days for a fact, and why it needs review."""

    fact: str
    value: int
    expected: list[int]
    chunk_id: str
    sentence: str
    reason: str


def expected_values(profile: StoreProfile) -> dict[str, list[int]]:
    """The numbers the profile declares for each checked fact."""
    return {
        "return_window_days": [profile.returns.window_days],
        "refund_days": [profile.returns.refund_days],
        "processing_business_days": sorted(set(profile.shipping.processing_business_days)),
    }


def _value(token: str) -> int:
    """'14' or 'catorce' -> 14."""
    return int(token) if token.isdigit() else NUMBER_WORDS[token.lower()]


def _mentions(chunk: PolicyChunk) -> list[tuple[str, int, str]]:
    """(fact, value, sentence) for each 'N days' whose preceding words name a fact."""
    found = []
    for sentence in re.split(r"(?<=[.!?;])\s+", chunk.content):
        for match in _DAYS.finditer(sentence):
            before = " ".join(sentence[:match.start()].split()[-WINDOW_WORDS:]).lower()
            # The closest keyword wins, so "refunds are issued 14 days after the return
            # arrives" counts for refunds, not for the return window.
            best = None
            for fact, pattern in FACT_KEYWORDS.items():
                hits = list(re.finditer(pattern, before))
                if hits and (best is None or hits[-1].start() > best[1]):
                    best = (fact, hits[-1].start())
            if best:
                found.append((best[0], _value(match.group(1)), sentence.strip()))
    return found


def check(profile: StoreProfile, chunks: list[PolicyChunk]) -> list[Finding]:
    """All mentions that contradict the profile or each other."""
    expected = expected_values(profile)
    mentions = [(fact, value, chunk.id, sentence)
                for chunk in chunks for fact, value, sentence in _mentions(chunk)]
    findings = []
    for fact, value, chunk_id, sentence in mentions:
        others = {v for f, v, _, _ in mentions if f == fact and v != value}
        if value not in expected[fact]:
            reason = f"profile says {expected[fact]}"
        elif others:
            reason = f"other policy sentences say {sorted(others)}"
        else:
            continue
        findings.append(Finding(fact, value, expected[fact], chunk_id, sentence, reason))
    return findings


def main() -> None:
    """Command-line entry point: print profile warnings and policy contradictions."""
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store-dir", type=Path, help="default: STORE_DIR or the demo shop")
    parser.add_argument("--strict", action="store_true", help="exit 1 if anything is found")
    args = parser.parse_args()
    if args.store_dir is None:
        from quilora.config import load_settings

        args.store_dir = Path(load_settings().store_dir)
    profile = load_profile(str(args.store_dir))
    findings = check(profile, load_policies(args.store_dir / "policies"))
    warnings = profile.warnings()

    print(f"Store: {profile.name} ({args.store_dir})")
    for w in warnings:
        print(f"  WARNING  {w}")
    for f in findings:
        print(f"  REVIEW   {f.fact}={f.value} in {f.chunk_id}: {f.reason}\n"
              f"           \"{f.sentence}\"")
    if not warnings and not findings:
        print("  OK: policies agree with the profile.")
    sys.exit(1 if args.strict and (warnings or findings) else 0)


if __name__ == "__main__":
    main()
