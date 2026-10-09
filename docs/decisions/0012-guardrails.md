# 0012. Guardrails: defence in depth, deterministic checks, block only on high precision

- **Status:** Proposed
- **Date:** 2026-10-09
- **Author:** Ignacio Rodríguez Caro

## Context

Threats for a customer-support agent: prompt injection (direct, in the chat, and indirect,
inside data such as an order note), leaking another customer's data, inventing discounts
or refunds, leaking the system prompt, collecting unnecessary personal data, and drifting
off-topic.

## Options

1. **Prompt rules only**: necessary but not sufficient; a request, not a control.
2. **An LLM classifier on every input and output**: catches paraphrases, but adds a model
   call (latency and cost) per turn and is itself injectable and non-deterministic.
3. **Defence in depth with deterministic layers**: authorisation in tools, regex/Luhn based
   redaction, canary-based leak detection and output checks, with an LLM classifier only
   as a later, measured addition.

## Decision

Option 3:

| Layer | Mechanism | Action |
|-------|-----------|--------|
| Tools | Order verification, session binding, confirmation tokens | Refuse (strongest) |
| Data | Untrusted fields wrapped and labelled | Inform the model |
| Input | Card numbers (Luhn), IBAN, DNI/NIE | Redact before model, logs and history |
| Input | Injection phrases (ES/EN) | Flag only (false positives would block real customers) |
| Output | Prompt canary or rule text in the reply | Block, replace with safe text |
| Output | Code-like token near "code/descuento" not present in any tool result | Block |
| Output | Amounts not present in tool results or customer messages | Flag (sums are legitimate) |
| Output | Email address in the reply | Flag |
| Prompt | Rules, scope, confidentiality | Ask |

Off-topic handling stays in the prompt and is measured by eval cases.

## Consequences

- The security story does not depend on detection: even an undetected injection cannot
  cross a tool's authorisation check (tested in `test_guardrails.py`).
- Flags are attached to each turn (API response, traces, eval report), so false-positive
  and false-negative rates can be measured before deciding to block more.
- Known gaps: regexes miss creative phrasing and other languages; the amount check cannot
  tell a correct sum from an invented number. An LLM-based classifier is a next step, to
  be justified by eval numbers.
