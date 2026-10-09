# Evaluation

_Author: Ignacio Rodríguez Caro_

The evaluation suite is what turns this from a demo into something that can be changed
safely. Every change to the prompt, a tool, the model or retrieval is measured against
the same cases and compared with the previous run.

## Three levels

| Level | What | Where | Needs API key |
|-------|------|-------|---------------|
| Unit and integration tests | Tools, rules, loop mechanics with a scripted model | `tests/` | No |
| Retrieval benchmark | Hit@k / MRR of policy search on labelled queries | `make compare-search` | No |
| Agent evaluation | Real model, real tools, 83 conversations | `make eval` | Yes |

## Agent evaluation

- **Cases**: `evals/cases/*.yaml`, 83 cases in 12 categories (product search, sizing, stock,
  order status, returns, policies, off-topic, ambiguous, attacks, handoff, multi-turn, delivery), 8
  of them multi-turn. Each case lists customer turns and expectations.
- **Deterministic graders** (`src/quilora/evals/graders.py`): tools called or not called,
  tool arguments (`{"max_price_eur": {"lte": 60}}`), error codes, reply contains / does not
  contain / matches, reply language, handoff happened, return created in the database,
  guardrail flags present or absent. Per-turn expectations are supported (e.g. "no return
  must exist after turn 2").
- **Isolation**: each case starts from the same data (runtime tables are truncated).
- **Repeats**: `--repeat N` runs each case N times; a case passes only if every attempt
  passes, and the report shows consistency (`2/3`). LLMs are not deterministic, so one green
  run is weaker evidence than three.
- **Report**: pass rate per category, estimated cost per conversation, p50/p95 latency per
  turn, tokens, failures with the failed checks, the tools used and the last reply.
- **Baseline**: `evals/baseline.json`. Each report states what changed (model, prompt hash,
  tools hash, retrieval backend) and lists regressions and fixes case by case.
- **CI**: `.github/workflows/evals.yml` runs on pull requests that touch the agent, tools,
  search or cases (and on demand with another model), fails below 85% or on any regression,
  and publishes the report in the job summary.

## When a model can grade another model, and when a human must

LLM-as-judge is useful for properties that are real but not string-matchable: "is the reply
faithful to the tool results?", "does it acknowledge the complaint without promising
compensation?", "does the handoff summary let an agent continue?". It works well when:

- the rubric is **narrow and binary** ("does the reply promise a refund? yes/no") rather
  than a 1-10 score;
- the judge sees the **evidence** (tool results), so it checks faithfulness instead of
  plausibility;
- the judge is a **different, cheaper model** with its own prompt, to limit cost and
  self-preference bias;
- it is used **on top of** deterministic checks, never instead of them for things code can
  check (a tool was called, a return exists, a number matches).

A human is needed when:

- **creating and changing the ground truth**: the cases and rubrics encode business
  decisions (what should happen), which only the business can own;
- **calibrating the judge**: before trusting it, compare its verdicts with human labels on
  a sample (30-50 transcripts) and measure agreement; repeat after changing the judge
  model or rubric;
- **high-stakes categories** (money, personal data, legal statements): sample production
  conversations for human review regardless of scores;
- **new failure modes**: reading failing transcripts is how new cases are discovered.
  Metrics tell you *that* something changed; transcripts tell you *what*.

In this repository the judge is optional (`--judge`), only applies to cases that define a
`judge` rubric, and its verdict appears as one more check named `judge`.

## Known limitations

- 83 cases is a small sample: one case is ~1.2 points. Treat small deltas as noise; use
  `--repeat` before drawing conclusions.
- Regex checks are brittle to phrasing; they were written to be permissive (alternatives,
  accent- and case-insensitive) and should be reviewed when they fail.
- Language detection is a heuristic tuned for Spanish vs English only.
- Cost figures use an unverified price table until `agent/pricing.py` is updated from the
  official pricing page.
