# 0015. Synchronous FastAPI with sessions in Postgres and optimistic locking

- **Status:** Proposed
- **Date:** 2026-10-09

## Context

The widget needs an HTTP endpoint that keeps a conversation per session. The agent, the
Anthropic client and the database pool are synchronous. Several API replicas may run
behind a load balancer.

## Options for concurrency model

1. **Sync endpoints** (FastAPI runs them in a thread pool): simple, matches the rest of the
   code; throughput limited by threads (fine for tens of concurrent conversations per
   process, which wait mostly on the model API).
2. **Async end to end** (`AsyncAnthropic`, `psycopg` async, async loop): better for many
   concurrent idle connections; every layer must be async, more complex tests.

## Options for session storage

1. **In-memory dict**: lost on restart, not shared between replicas.
2. **Redis**: fast, TTLs built in; another service to run.
3. **Postgres JSONB row per conversation**: durable, shared, transactional with the rest
   of the data, already running.

## Decision

Sync endpoints, sessions in Postgres (`chat_sessions`) with an integer `version`
(optimistic locking). A concurrent update returns HTTP 409 instead of silently losing a
turn. A turn is not wrapped in a long transaction or row lock, because it lasts seconds.

## Consequences

- Restarting or scaling the API keeps conversations.
- Two simultaneous messages in the same conversation: one wins, the other gets 409 and the
  widget asks to resend. Side effects of the losing turn (a ticket) still happened; tools
  are idempotent, so a retry does not duplicate them.
- Conversations contain personal data: `purge_older_than(days)` is provided for a scheduled
  retention job.
- Moving to async is a contained change (model client, DB pool, loop signature) if load
  tests show thread exhaustion.
