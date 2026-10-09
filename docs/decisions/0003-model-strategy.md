# 0003. One capable model for the agent loop, no intent router

- **Status:** Proposed
- **Date:** 2026-10-09

## Context

A common pattern is to route each message through a small, cheap model that classifies the
intent, and only then call a larger model. Model IDs used here were verified against the
`anthropic` Python SDK 1.12.1 type definitions: `claude-sonnet-5-5`, `claude-haiku-5-5`,
`claude-opus-5-5`. Prices change; the source of truth is
<https://platform.claude.com/docs/en/about-claude/pricing>.

## Options

1. **Single capable model (Sonnet) runs the whole loop**
   - Pros: one call path; the model already chooses tools, which *is* intent
     classification; fewer failure points; simpler evaluation.
   - Cons: every turn pays the larger model's price.
2. **Router (Haiku) + worker (Sonnet)**
   - Pros: cheap path for trivial turns (greetings, off-topic).
   - Cons: an extra network round trip on every turn (latency is added, not saved, for
     the turns that need the big model); two prompts to maintain; misroutes become a new
     failure class; the router needs its own eval set.
3. **Single small model (Haiku) for everything**
   - Pros: lowest cost and latency.
   - Cons: risk of lower tool-selection accuracy and weaker instruction following under
     adversarial input. Unknown until measured.

## Decision

Option 1 by default, with the model configurable (`AGENT_MODEL`). Haiku is not rejected: the
evaluation suite runs the same cases against both models and the decision is revisited with
numbers (pass rate per category, cost per conversation, p50/p95 latency).

Prompt caching (`cache_control`) is enabled so the static prefix (system prompt + tool
definitions) is not paid in full on every iteration of the loop.

## Consequences

- Cost and latency are optimised with caching and short outputs before adding routing.
- If evals show Haiku matches Sonnet on most categories, the cheaper option becomes the
  default, or a router is introduced only for categories where it is proven safe.
- The judge model for LLM-as-judge grading is a separate setting (`JUDGE_MODEL`).
