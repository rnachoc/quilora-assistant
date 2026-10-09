# 0011. Handoff to a human as an idempotent support ticket with a model-written summary

- **Status:** Proposed
- **Date:** 2026-10-09

## Context

Some cases must go to a person: complaints, money disputes, defective items, lost
parcels, anything the assistant cannot do, or simply because the customer asks. The
person picking up the case should not have to ask the customer everything again.

## Options

1. **Tell the customer to email support**: no integration; the customer repeats the story.
2. **Ticket with the full transcript**: complete, but long, noisy and full of personal data.
3. **Ticket with a structured reason and a model-written summary** (plus the session ID to
   open the transcript if needed).

## Decision

Option 3. `handoff_to_human` validates a reason from a fixed list, a summary of 30-1500
characters written for the agent, an optional order number (flagged as verified or not)
and the customer's email only if they gave it. Code-level rules: one open ticket per
conversation (repeated calls append to it), and complaints and money disputes are always
`high` priority whatever the model chose.

## Consequences

- The summary quality is evaluated: eval cases check that a handoff happens when it should
  and that the summary mentions the order and the request (LLM-as-judge rubric).
- Integrating a real helpdesk (Zendesk, Freshdesk) means replacing one SQL insert with an
  API call or an event on a queue; the tool contract does not change.
