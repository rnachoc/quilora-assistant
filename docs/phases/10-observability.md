# Phase 10: Observability (traces, cost, latency)

## Concept

A **trace** is the tree of operations that served one request; each node is a **span**
with a start, a duration and attributes. For an agent the interesting tree is:

```
chat.turn                              2.9 s   tokens 3.1k in / 180 out   $0.006
├── chat claude-sonnet-5-5             1.2 s   finish: tool_use
├── execute_tool get_order_status      9 ms    order_id=1043 email=l***@example.com
├── execute_tool search_policies       4 ms
└── chat claude-sonnet-5-5             1.6 s   finish: end_turn
```

It answers the production questions directly: why was this turn slow (model or tools?),
why was it expensive (how many iterations, was the cache used?), what did the agent do for
this customer (which tools, which errors)?

**OpenTelemetry** is the vendor-neutral standard for producing traces; **OTLP** is its
wire protocol; the **GenAI semantic conventions** give standard names for LLM attributes so
any backend understands them.

## What was built

- `src/quilora/observability.py`: tracer setup (OTLP/HTTP and/or console), email redaction.
- `agent/loop.py`: spans for the turn, each model call and each tool call.
- `docker-compose.yml`: Jaeger all-in-one; the API exports to it.
- Tests with an in-memory exporter: span tree, attributes, redaction, error status.
- Verified end to end against a local OTLP endpoint (`POST /v1/traces` received).

## Where the numbers show up

| Place | What |
|-------|------|
| Jaeger (`localhost:16686`) | Per-turn trace tree with durations and attributes |
| API response `meta` | Tools, iterations, latency, tokens, cost, guardrail flags |
| Widget "Details" toggle | The same `meta`, rendered under each reply |
| Evaluation report | p50/p95 latency per turn, cost per conversation, tokens per run |
| Logs | One structured line per turn |

## Cost, explained

Cost per turn = Σ over model calls of (input × price_in + cache writes × 1.25 × price_in +
cache reads × 0.1 × price_in + output × price_out). Turns with tools make several model
calls and each one re-sends the conversation, which is why prompt caching matters. The price
table in `agent/pricing.py` must be checked against the official pricing page.
