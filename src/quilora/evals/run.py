"""Run the evaluation suite against the real model and the seeded database.

    python -m quilora.evals.run --validate              # check case files only (no API calls)
    python -m quilora.evals.run                         # all cases, compare with the baseline
    python -m quilora.evals.run --category attacks --repeat 3
    python -m quilora.evals.run --model claude-haiku-5-5 --judge
    python -m quilora.evals.run --save-baseline         # accept this run as the new baseline

Every run writes evals/results/<timestamp>/{results.json,report.md}.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

from quilora.agent.pricing import PRICING_VERIFIED
from quilora.agent.session import Conversation
from quilora.bootstrap import build_agent
from quilora.config import load_settings
from quilora.db import Database
from quilora.evals.cases import Case, load_cases
from quilora.evals.graders import CaseRun, Check, grade
from quilora.evals.judge import Judge
from quilora.evals.report import render_report
from quilora.paths import EVALS_DIR, PROJECT_ROOT
from quilora.seed import reset_writes

ROOT = PROJECT_ROOT
RESULTS_DIR = EVALS_DIR / "results"
BASELINE = EVALS_DIR / "baseline.json"


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,  # noqa: S607
                              text=True, check=True, cwd=ROOT).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _sha(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def _count(db: Database, table: str, session_id: str) -> int:
    with db.connection() as conn:
        return conn.execute(f"SELECT count(*) AS n FROM {table} WHERE session_id = %s",  # noqa: S608
                            (session_id,)).fetchone()["n"]


def play(agent, db: Database, case: Case, attempt: int, judge: Judge | None) -> dict:
    with db.connection() as conn:
        reset_writes(conn)  # every case starts from the same data
    conv = Conversation(id=f"eval-{case.id}-{attempt}")
    run = CaseRun(turns=[])
    checks: list[Check] = []
    try:
        for i, turn in enumerate(case.turns, start=1):
            result = agent.run_turn(conv, turn.user)
            run.turns.append(result)
            if turn.expect:
                snapshot = CaseRun(turns=[result],
                                   returns_created=_count(db, "return_requests", conv.id))
                checks += grade(turn.expect, [result], snapshot, scope=f"turn{i}")
        run.returns_created = _count(db, "return_requests", conv.id)
        run.tickets_created = _count(db, "support_tickets", conv.id)
        checks += grade(case.expect, run.turns, run, scope="final")
        if judge and case.judge:
            checks.append(judge.evaluate(case.judge, conv.messages))
    except Exception as exc:  # a crash is a failed case, not a crashed suite
        run.error = f"{type(exc).__name__}: {exc}"
        checks.append(Check("no_exception", False, run.error))

    return {
        "passed": all(c.passed for c in checks),
        "checks": [asdict(c) for c in checks],
        "error": run.error,
        "turns": [
            {
                "user": case.turns[i].user,
                "reply": r.reply,
                "stop_reason": r.stop_reason,
                "tools": [{"name": c.name, "input": c.input, "error": c.error_code}
                          for c in r.tool_calls],
                "iterations": r.iterations,
                "latency_ms": round(r.latency_ms),
                "cost_usd": r.cost_usd,
                "usage": r.usage.as_dict(),
                "flags": r.flags,
                "handed_off": r.handed_off,
            }
            for i, r in enumerate(run.turns)
        ],
    }


def summarise(cases: list[dict]) -> dict:
    by_cat: dict[str, Counter] = defaultdict(Counter)
    for c in cases:
        by_cat[c["category"]]["n"] += 1
        by_cat[c["category"]]["passed"] += int(c["passed"])
    turns = [t for c in cases for a in c["attempts"] for t in a["turns"]]
    latencies = sorted(t["latency_ms"] for t in turns) or [0]
    costs = [t["cost_usd"] or 0 for t in turns]
    usage = Counter()
    for t in turns:
        usage.update(t["usage"])
    attempts = sum(len(c["attempts"]) for c in cases) or 1
    n = len(cases) or 1
    return {
        "total": len(cases),
        "passed": sum(c["passed"] for c in cases),
        "pass_rate": round(sum(c["passed"] for c in cases) / n, 4),
        "by_category": {
            k: {"n": v["n"], "passed": v["passed"], "rate": round(v["passed"] / v["n"], 4)}
            for k, v in sorted(by_cat.items())
        },
        "cost_usd_total": round(sum(costs), 4),
        "cost_usd_per_conversation": round(sum(costs) / attempts, 5),
        "latency_ms_p50": statistics.median(latencies),
        "latency_ms_p95": latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))],
        "turns": len(turns),
        "tokens": dict(usage),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--validate", action="store_true", help="validate case files and exit")
    parser.add_argument("--category", action="append", help="only these categories")
    parser.add_argument("--id", action="append", help="only these case ids")
    parser.add_argument("--limit", type=int, help="run at most N cases")
    parser.add_argument("--repeat", type=int, default=1,
                        help="attempts per case; a case passes only if every attempt passes")
    parser.add_argument("--model", help="override AGENT_MODEL")
    parser.add_argument("--judge", action="store_true", help="enable the LLM judge rubrics")
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--save-baseline", action="store_true")
    parser.add_argument("--min-pass-rate", type=float, default=0.0)
    parser.add_argument("--fail-on-regression", action="store_true")
    args = parser.parse_args()

    cases = load_cases()
    if args.validate:
        counts = Counter(c.category for c in cases)
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        print(f"{len(cases)} valid cases: {summary}")
        return
    if args.category:
        cases = [c for c in cases if c.category in args.category]
    if args.id:
        cases = [c for c in cases if c.id in args.id]
    if args.limit:
        cases = cases[: args.limit]

    settings = load_settings()
    if args.model:
        settings = replace(settings, agent_model=args.model)
    db = Database(settings.database_url)
    agent = build_agent(settings, db=db)
    judge = Judge(settings.anthropic_api_key, settings.judge_model) if args.judge else None

    meta = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "model": settings.agent_model,
        "judge_model": settings.judge_model if judge else None,
        "prompt_sha": _sha(agent.system_prompt()),
        "tools_sha": _sha(json.dumps(agent.registry.definitions(), sort_keys=True)),
        "policy_search_backend": settings.policy_search_backend,
        "repeat": args.repeat,
        "pricing_verified": PRICING_VERIFIED,
    }

    results = []
    started = time.perf_counter()
    for i, case in enumerate(cases, start=1):
        attempts = [play(agent, db, case, a, judge) for a in range(1, args.repeat + 1)]
        passed = all(a["passed"] for a in attempts)
        results.append({"id": case.id, "category": case.category,
                        "description": case.description, "passed": passed,
                        "consistency": f"{sum(a['passed'] for a in attempts)}/{len(attempts)}",
                        "attempts": attempts})
        print(f"[{i:>3}/{len(cases)}] {'PASS' if passed else 'FAIL'} {case.id}", flush=True)
    meta["duration_s"] = round(time.perf_counter() - started, 1)

    payload = {"meta": meta, "summary": summarise(results), "cases": results}
    baseline = json.loads(args.baseline.read_text()) if args.baseline.exists() else None
    report = render_report(payload, baseline)

    out = RESULTS_DIR / meta["timestamp"].replace(":", "")
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    (out / "report.md").write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"Saved to {out.relative_to(ROOT)}")

    if args.save_baseline:
        args.baseline.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"Baseline updated: {args.baseline.relative_to(ROOT)}")

    failed = payload["summary"]["pass_rate"] < args.min_pass_rate
    if args.fail_on_regression and baseline:
        from quilora.evals.report import compare

        failed |= bool(compare(payload, baseline)["regressions"])
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
