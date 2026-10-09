# 0006. Tool design: few tools, invariants enforced in code

- **Status:** Proposed
- **Date:** 2026-10-09
- **Author:** Ignacio Rodríguez Caro

## Context

The model never executes anything. It *proposes* a tool call; our code validates it, decides
whether it is allowed, executes it and returns a result. The quality and safety of the
assistant depend more on how the tools are shaped than on prompt wording.

## Options

1. **Many fine-grained tools** (one per query type): precise, but the model must choose
   among dozens of similar options and the system prompt grows.
2. **One generic tool** (e.g. "run SQL"): flexible, but impossible to secure or evaluate.
3. **Few task-shaped tools with strict inputs** (eight tools mapped to customer jobs).

## Decision

Option 3, with these rules:

1. **Inputs are validated with Pydantic** before any handler runs. Invalid input returns a
   structured error the model can act on, never a stack trace.
2. **Security invariants live in code, not in the prompt.** Examples: `get_order_status`
   requires order number *and* email and returns the same error for "not found" and
   "wrong email" (no enumeration); `create_return_request` only works on an order verified
   earlier in the same session and only executes with a confirmation token issued in a
   previous turn.
3. **Errors are designed for the model**: `{"error": {"code", "message", "hint"}}`, where the
   hint says what to do next (ask the customer, retry, escalate).
4. **Outputs are minimal and explicit**: stock is reported as a level, not raw counts;
   emails are masked; customer-provided free text is labelled as untrusted data.
5. **Exactly one tool mutates business data** (`create_return_request`); `handoff_to_human`
   only creates a support ticket.
6. **One registry, two transports**: the same tool specs are served to the agent loop and
   to the MCP server.

## Consequences

- Prompt-injection attempts cannot reach other customers' data even if the model is fooled,
  because the code refuses.
- Tool descriptions are treated as product copy: reviewed and covered by evaluation cases.
