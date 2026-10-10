# 0023. A scripted demo model for the free hosted demo

- **Status:** Accepted
- **Date:** 2026-10-10
- **Author:** Ignacio Rodríguez Caro

## Context

ADR 0022 put the assistant on free hosting, but every answer from Claude is a paid API call
and the hosted demo must cost nothing. Without a model the site would show a widget that
cannot answer anything.

## Options

1. **Claude with a prepaid budget and spending caps**: the real product, but not free.
2. **A free tier of another model provider**: real answers, but needs a provider adapter,
   a new evaluation run, and free tiers commonly allow the provider to use the data. It
   also stops being a Claude demo.
3. **A scripted model behind the same `ModelClient` interface**: zero cost and nothing to
   abuse, but it understands only a fixed set of questions.
4. **No live site**: repository and a recorded video only.

## Decision

Option 3 for the hosted site (`AGENT_MODE=scripted`), with the live system shown through
Claude Desktop and the MCP server (ADR 0014) on the owner's subscription.

`ScriptedDemoModel` implements the same protocol as `AnthropicModelClient`, so the agent
loop, tool validation, Postgres queries, session-bound order verification, two-phase return
confirmation, input and output guardrails, sessions and traces all run unchanged. Only the
choice of tool, arguments and reply text is scripted:

- Nine sample questions (catalog search, stock, size advice, return window with citation,
  order status, someone else's order, a return with confirmation, a manipulation attempt,
  handoff), matched by keywords so small rewordings still work.
- Replies are built only from this turn's tool results (prices, stock, dates, citations),
  never from hard-coded facts, so the data shown is the database's.
- Anything else gets an honest "this is a scripted demo" answer. The widget shows a "Demo"
  badge and the sample questions as buttons (`GET /api/store` returns them).
- The demo resets returns, tickets and sessions on each start, so the sample return can be
  tried again after the free instance wakes up.

## Consequences

- The hosted demo has no model cost and no API key to leak or exhaust.
- It demonstrates the project's main claim ("the model proposes, the code validates,
  executes and decides") very literally: swapping the model does not change what the
  system allows.
- It does not demonstrate language understanding; reviewers must not mistake it for the
  real assistant, hence the badge and the explicit fallback text.
- Switching the hosted site to Claude is configuration only: `AGENT_MODE=live` plus
  `ANTHROPIC_API_KEY`.
- The script is code to maintain: tests run every sample question through the real loop
  and database (`tests/test_scripted_demo.py`).
