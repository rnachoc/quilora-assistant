# 0004. Hand-written agent loop on the Messages API

- **Status:** Proposed
- **Date:** 2026-10-09
- **Author:** Ignacio Rodríguez Caro

## Context

An agent is a loop: call the model, execute the tools it requests, send results back, repeat
until it answers. This can be written by hand or delegated to a framework (LangChain,
LlamaIndex, the Claude Agent SDK, or the SDK's tool runner helper).

## Options

1. **Hand-written loop (~150 lines)**
   - Pros: every step is visible and testable; full control over limits (max iterations,
     timeouts), error shaping, confirmation gates, tracing and cost accounting; no
     framework upgrade churn.
   - Cons: we own the code; features like streaming need extra work.
2. **General-purpose framework (LangChain / LlamaIndex)**
   - Pros: many integrations; quick prototypes.
   - Cons: deep abstraction layers; harder to debug and to explain; the behaviour that
     matters here (who decides, what is validated) would live in framework internals.
3. **Claude Agent SDK / SDK tool runner**
   - Pros: official, well maintained, less code.
   - Cons: the Agent SDK targets autonomous agents with file/shell tools, which is far more
     power than a customer-support bot needs; the tool runner hides the loop I want to
     learn and instrument.

## Decision

Option 1. The loop is the core of the project and must be explainable line by line.

## Consequences

- `src/quilora/agent/loop.py` contains all control flow; tests drive it with a scripted fake
  model, so its behaviour is verified without network calls.
- If the project grows (streaming, parallel tools, many agents), adopting the tool runner or
  the Agent SDK is reconsidered in a new ADR.
