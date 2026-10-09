# Phase 7: Evaluation and CI

## Concept

A unit test asks "does this function return X?". An **evaluation** asks "given this
customer message, does the whole system (model + prompt + tools + data) behave as the
business expects?". Because the model is probabilistic, we measure rates over many cases
instead of asserting one output, and we compare every change with a baseline.

What makes an eval case good:

- It checks **behaviour**, not wording: which tool was called with which arguments, what
  ended up in the database, whether a handoff happened.
- It encodes a **business decision** ("a question after the summary is not a yes").
- It fails for **one** reason, so failures are easy to read.

## What was built

| Path | Content |
|------|---------|
| `evals/cases/*.yaml` | 72 cases, 11 categories, 15 multi-turn |
| `src/quilora/evals/cases.py` | Validated case schema |
| `src/quilora/evals/graders.py` | Deterministic checks |
| `src/quilora/evals/judge.py` | Optional LLM judge (structured output, JSON fallback) |
| `src/quilora/evals/run.py` | Runner: isolation, repeats, cost, latency, baseline, exit code |
| `src/quilora/evals/report.py` | Markdown report and regression diff |
| `.github/workflows/ci.yml` | Lint, secrets, tests on Postgres, case validation, FTS benchmark |
| `.github/workflows/evals.yml` | Real-model evals on relevant PRs, fails on regressions |
| `docs/evaluation.md` | Method, judge vs human review, limitations |

## First run (to do with an API key)

```bash
make eval-baseline        # run once and save evals/baseline.json; commit it
make eval                 # after any change: compare with the baseline
python -m quilora.evals.run --model claude-haiku-5-5   # the ADR 0003 comparison
```

Read the failures before touching the prompt. Typical outcomes and the right fix:

| Failure | Usually means | Fix in |
|---------|---------------|--------|
| Wrong or missing tool | Tool description unclear | Tool `description` |
| Right tool, wrong arguments | Schema or field descriptions unclear | Pydantic `Field(description=...)` |
| Correct behaviour, check fails | The check is too strict | The case |
| Unsafe action attempted | The code should have refused | The tool (never only the prompt) |
