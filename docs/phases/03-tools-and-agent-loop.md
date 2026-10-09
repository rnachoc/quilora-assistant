# Phase 3: Read-only tools and the agent loop

_Author: Ignacio Rodríguez Caro_

## Concept

**Tool use** works like this: with each request we send the model a list of tools (name,
description, JSON Schema of the input). When the model decides it needs one, it stops with
`stop_reason: "tool_use"` and returns one or more `tool_use` blocks (`id`, `name`,
`input`). The model has executed nothing. Our code runs the tool and sends the result back
in the next `user` message as a `tool_result` block with the same `id`. The model reads it
and either calls another tool or writes the answer. That cycle is the **agent loop**.

Three things make the loop production-grade rather than a demo:

1. **Limits.** A maximum number of model calls per turn (`AGENT_MAX_ITERATIONS`), a
   timeout per tool (`TOOL_TIMEOUT_SECONDS`) plus a Postgres `statement_timeout`, a model
   timeout with SDK retries, and caps on message length and conversation length.
2. **Errors the model can use.** Every failure becomes
   `{"error": {"code", "message", "hint", "retryable"}}` with `is_error: true`. The hint
   tells the model what to do next ("ask for the email", "offer a transfer"). Stack traces
   never reach the model.
3. **A valid history, always.** Every `tool_use` gets its `tool_result`; if the model API
   fails or the budget runs out, the code closes the turn with its own message, so the next
   turn works. A `tool_use` truncated by `max_tokens` is never executed.

## What was built

| File | Responsibility |
|------|----------------|
| `tools/base.py` | `ToolSpec`, `ToolRegistry` (lookup → Pydantic validation → timeout → error shaping), `SessionState` |
| `tools/catalog.py` | `search_products`, `get_product`, `check_stock`, `get_size_recommendation` |
| `tools/orders.py` | `get_order_status` with two-factor identification, no enumeration, lockout |
| `domain/sizing.py` | Deterministic size recommendation (measurements or a height/weight estimate) |
| `domain/returns.py` | Return eligibility rules (30-day window, final sale, already returned) |
| `agent/loop.py` | The loop, limits and fallbacks |
| `agent/prompts/system.md` | Behaviour rules for the assistant |
| `cli.py` | `python -m quilora.cli` |

## Decisions worth defending

- **Input schemas come from Pydantic models**, so the schema the model sees and the
  validation the code applies cannot drift apart. `extra="forbid"` rejects invented
  parameters.
- **Security lives in the tool, not the prompt.** `get_order_status` returns the *same*
  error for "order does not exist" and "email does not match", locks after 3 failures and
  records the verified order in `SessionState`, which later gates returns.
- **Stock is exposed as levels**; exact counts only when low ("only 2 left").
- **Size is computed, not reasoned.** The model collects data and explains; code decides.
- **Untrusted text is labelled.** Customer delivery notes are wrapped in
  `untrusted_customer_note` with a warning, so the model sees provenance explicitly.
- **Search falls back** from "all words" to "any word" and says so (`match: some_terms`), so
  the model can tell the customer the results are approximate.

## How to verify

```bash
make test                       # 50+ tests: tools against Postgres, loop with a fake model
python -m quilora.cli --verbose # needs ANTHROPIC_API_KEY
```

Try: "¿Tenéis vestidos de lino por menos de 60 €?", then "¿Queda la M en negro del
pantalón Iris?", then "Mido 1,68 y peso 60 kg, ¿qué talla me pido?". Watch which tools are
called and how many model calls each turn needs.
