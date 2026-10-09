# 0013. Evaluation: deterministic graders first, optional LLM judge, baseline in the repo

- **Status:** Proposed
- **Date:** 2026-10-09
- **Author:** Ignacio Rodríguez Caro

## Context

Prompt, tool and model changes alter behaviour in ways that unit tests cannot see. We need
a repeatable measure of "does the assistant do the right thing" that runs in CI and
compares versions.

## Options

1. **Manual testing**: cheap to start, impossible to compare over time.
2. **LLM-as-judge for everything**: flexible, but costly, non-deterministic, and it hides
   simple failures (a missing tool call) behind a fuzzy score.
3. **Deterministic graders on observable behaviour** (tool calls, arguments, database
   effects, reply patterns, guardrail flags), plus a narrow optional judge for qualities
   only a reader can assess.
4. **Off-the-shelf eval platform** (Langfuse, Braintrust, promptfoo, etc.): dashboards and
   dataset management; another dependency and service to learn before the basics are clear.

## Decision

Option 3, implemented in ~400 lines (`src/quilora/evals/`), YAML cases in `evals/cases/`, a
committed baseline, and a GitHub Actions workflow that fails on regressions. The judge uses
a different, cheaper model (`JUDGE_MODEL`) and binary rubrics.

## Consequences

- Most checks are free to compute and fully explainable ("not_called:get_order_status").
- The suite checks *outcomes in the database* (was a return created?), which is what the
  business cares about, not only the text.
- Moving to an eval platform later is straightforward: cases and results are plain JSON/YAML.
- Running against the real model costs money; CI runs it only on relevant changes.
