# 0017. Observability with OpenTelemetry traces and GenAI semantic conventions

- **Status:** Proposed
- **Date:** 2026-10-09

## Context

For each turn we need to know which model calls and tools ran, with which arguments, how
long each took, how many tokens were used and what it cost, and to find a conversation
again when a customer complains. The target company uses OpenTelemetry.

## Options

1. **Structured logs only**: simple; no causal tree; hard to see where time goes.
2. **LLM observability SaaS (Langfuse, LangSmith, Datadog LLM)**: rich UI and prompt
   playgrounds; vendor lock-in for the data format and, for SaaS, customer data leaves our
   infrastructure.
3. **OpenTelemetry SDK + OTLP exporter**, GenAI semantic conventions for attribute names,
   any OTLP backend (Jaeger locally; Tempo, Honeycomb, Datadog or an LLM tool with OTLP
   ingestion later).

## Decision

Option 3. One trace per turn: `chat.turn` → `chat {model}` per model call →
`execute_tool {name}` per tool call. Attributes: GenAI conventions
(`gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`,
`gen_ai.usage.input_tokens`, `gen_ai.tool.name`, ...) plus `quilora.*` for cache tokens,
cost, flags and redacted tool arguments. No message text is recorded. Without an exporter
configured, the tracer is a no-op.

## Consequences

- Jaeger runs in Docker Compose; traces are visible at `localhost:16686`.
- The same numbers appear in the API response (`meta`) and in the evaluation report, so
  development, CI and production use one vocabulary.
- The GenAI conventions are still in "Development" status: attribute names may change.
- Next steps: OTel metrics (histograms for latency and cost per turn, counters for
  handoffs and guardrail flags), FastAPI auto-instrumentation so the turn span becomes a
  child of the HTTP span, and sampling for high traffic.
