# 0010. Two-phase confirmation for returns, enforced in code

- **Status:** Proposed
- **Date:** 2026-10-09

## Context

`create_return_request` is the only tool that changes business data. The requirement is
"ask the customer for explicit confirmation". A prompt instruction is not a guarantee: the
model may skip the question, misread "vale, ¿y cuánto tarda?" as a yes, or be manipulated.

## Options

1. **Prompt only** ("always confirm before calling"): zero code; no guarantee, untestable.
2. **`confirmed: true` parameter**: the model sets the flag itself, so it proves nothing.
3. **Two-phase call with a token redeemable only in a later turn**: the first call validates
   and returns a summary plus a single-use token; the second call must carry that token and
   happen after a new customer message.
4. **Out-of-band confirmation button** in the UI that calls the API directly: the strongest
   guarantee (the model is not involved at all), but only works where we control the UI
   (not in MCP clients or plain-text channels).

## Decision

Option 3, implemented in `tools/returns.py`, with these checks in code: the order was
verified in this session; the token exists, belongs to this order and has not expired
(30 min); the current turn is later than the one that issued it; items and reason are
identical to the summary. Writes happen in one transaction with an audit entry.

Idempotency has two layers: a confirmed token remembers its return ID (replays return the
same ID), and a unique `idempotency_key` in Postgres stops concurrent duplicates.

## Consequences

- The model still interprets whether the customer's reply means "yes". The code guarantees
  that a customer reply *happened* after the summary was shown, not what it said. Eval
  cases cover ambiguous replies ("hmm, ¿y el envío?") and negative ones.
- Option 4 is the natural next step for the web widget: render the summary with
  Confirm/Cancel buttons that call the confirmation directly.
- Defective or wrong items are refused with `USE_HANDOFF` (Returns Policy §7), and the
  `reason` CHECK constraint in the database backs that rule.
