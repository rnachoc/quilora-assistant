# 0021. Check policy texts against the profile before going live

- **Status:** Proposed
- **Date:** 2026-10-09
- **Author:** Ignacio Rodríguez Caro

## Context

Shop policies are written over time, often by different people, and the numbers drift:
one return period in one section and a different one in another, or two processing times
in the same shipping policy. A retrieval-based assistant would quote whichever section it
happened to retrieve.

## Options

1. **Trust the texts**: answers change from one conversation to the next.
2. **Ask the model to reconcile contradictions at answer time**: it will pick one, with no
   one knowing.
3. **Detect contradictions before going live** and make a human resolve them; at answer
   time, tell the model not to choose between conflicting sections but to hand off.

## Decision

Option 3: `python -m quilora.store.consistency` (also `make check-store`) finds sentences
that state a number of days for a key fact (return window, refund time, processing time),
using the closest keyword in Spanish or English, and reports values that differ from the
profile or from each other. The prompt tells the model to say a policy is unclear and offer
a transfer when sections disagree.

## Consequences

- It is a heuristic review aid, not legal analysis, and reports some legitimate sentences
  ("the legal minimum is 14 days, we offer 30") on purpose.
- Covers three facts today; free-shipping thresholds and transit times per zone are the
  next ones to add.
