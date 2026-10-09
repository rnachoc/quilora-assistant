"""Markdown report and baseline comparison for evaluation runs.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations


def compare(current: dict, baseline: dict) -> dict:
    """Diff a run against the baseline: regressions, fixes, new cases and changed settings."""
    before = {c["id"]: c["passed"] for c in baseline["cases"]}
    now = {c["id"]: c["passed"] for c in current["cases"]}
    common = before.keys() & now.keys()
    return {
        "regressions": sorted(i for i in common if before[i] and not now[i]),
        "fixed": sorted(i for i in common if not before[i] and now[i]),
        "new_cases": sorted(now.keys() - before.keys()),
        "removed_cases": sorted(before.keys() - now.keys()),
        "changed": {k: (baseline["meta"].get(k), current["meta"].get(k))
                    for k in ("model", "prompt_sha", "tools_sha", "policy_search_backend")
                    if baseline["meta"].get(k) != current["meta"].get(k)},
    }


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def render_report(results: dict, baseline: dict | None) -> str:
    """Markdown report: pass rate per category, cost, latency, baseline diff and failures."""
    meta, summary = results["meta"], results["summary"]
    base_cats = baseline["summary"]["by_category"] if baseline else {}
    lines = [
        "# Evaluation report",
        "",
        f"- Model: `{meta['model']}` · commit `{meta['git_commit']}`"
        f" · prompt `{meta['prompt_sha']}` · tools `{meta['tools_sha']}`"
        f" · policy search `{meta['policy_search_backend']}`",
        f"- Attempts per case: {meta['repeat']} · duration {meta.get('duration_s', '?')} s",
        "",
        f"**Overall: {summary['passed']}/{summary['total']} ({_pct(summary['pass_rate'])})**",
        "",
        "| Category | Passed | Rate | vs baseline |",
        "|----------|--------|------|-------------|",
    ]
    for cat, m in summary["by_category"].items():
        delta = ""
        if cat in base_cats:
            d = m["rate"] - base_cats[cat]["rate"]
            delta = "=" if abs(d) < 1e-9 else f"{'+' if d > 0 else ''}{100 * d:.0f} pts"
        lines.append(f"| {cat} | {m['passed']}/{m['n']} | {_pct(m['rate'])} | {delta} |")

    warn = "" if meta.get("pricing_verified") else " (unverified price table, see pricing.py)"
    lines += [
        "",
        "## Cost and latency",
        "",
        f"- Estimated cost: ${summary['cost_usd_total']} total, "
        f"${summary['cost_usd_per_conversation']} per conversation{warn}",
        f"- Latency per turn: p50 {summary['latency_ms_p50']:.0f} ms, "
        f"p95 {summary['latency_ms_p95']:.0f} ms over {summary['turns']} turns",
        f"- Tokens: {summary['tokens']}",
    ]

    if baseline:
        diff = compare(results, baseline)
        lines += ["", "## Compared with baseline", ""]
        if diff["changed"]:
            lines += [f"- Changed `{k}`: `{a}` → `{b}`" for k, (a, b) in diff["changed"].items()]
        regressions = ", ".join(diff["regressions"]) or "none"
        fixed = ", ".join(diff["fixed"]) or "none"
        lines += [
            f"- Regressions ({len(diff['regressions'])}): {regressions}",
            f"- Fixed ({len(diff['fixed'])}): {fixed}",
        ]
        if diff["new_cases"]:
            lines.append(f"- New cases: {', '.join(diff['new_cases'])}")
    else:
        lines += ["", "_No baseline found. Save one with `--save-baseline`._"]

    failures = [c for c in results["cases"] if not c["passed"]]
    if failures:
        lines += ["", "## Failures", ""]
        for case in failures:
            attempt = next(a for a in case["attempts"] if not a["passed"])
            failed = [ch for ch in attempt["checks"] if not ch["passed"]]
            lines.append(f"### {case['id']} ({case['category']}, {case['consistency']} passed)")
            lines.append(f"{case['description']}")
            lines.append("")
            for ch in failed:
                lines.append(f"- ✗ `{ch['name']}` {ch['detail']}".rstrip())
            last = attempt["turns"][-1] if attempt["turns"] else None
            if last:
                tools = ", ".join(f"{t['name']}{'!' + t['error'] if t['error'] else ''}"
                                  for t in last["tools"]) or "none"
                reply = last["reply"].replace("\n", " ")[:400]
                lines += [f"- Last tools: {tools}", f"- Last reply: > {reply}", ""]
    return "\n".join(lines) + "\n"
