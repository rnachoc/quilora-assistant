# Architecture Decision Records

_Author: Ignacio Rodríguez Caro_

Each significant decision is recorded as a short ADR: **context, options, decision, consequences**.

Status values:

- **Proposed**: a default was chosen so work could continue; it is open for review.
- **Accepted**: reviewed and confirmed by the project owner.
- **Superseded**: replaced by a later ADR (linked).

| # | Title | Status |
|---|-------|--------|
| [0001](0001-record-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-agent-language-python.md) | Agent language: Python instead of Java + Spring AI | Proposed |
| [0003](0003-model-strategy.md) | One capable model for the agent loop, no intent router | Proposed |
| [0004](0004-no-agent-framework.md) | Hand-written agent loop on the Messages API | Proposed |
| [0005](0005-postgres-single-datastore.md) | PostgreSQL as the single datastore | Proposed |
| [0006](0006-tool-design-principles.md) | Tool design: few tools, invariants enforced in code | Proposed |
| [0007](0007-synthetic-data.md) | Fictional store, synthetic data, English catalog | Proposed |
| [0008](0008-policy-retrieval.md) | Policy retrieval: FTS first, vector and hybrid measured | Proposed |
| [0009](0009-local-embedding-model.md) | Local multilingual embedding model (fastembed) | Proposed |
| [0010](0010-two-phase-confirmation.md) | Two-phase confirmation for returns, enforced in code | Proposed |
| [0011](0011-handoff-tickets.md) | Handoff as an idempotent ticket with a model-written summary | Proposed |
| [0012](0012-guardrails.md) | Guardrails: defence in depth, deterministic checks | Proposed |
| [0013](0013-evaluation-strategy.md) | Evaluation: deterministic graders, optional LLM judge, baseline | Proposed |
| [0014](0014-mcp-read-only.md) | MCP server exposes read-only tools and policies | Proposed |
| [0015](0015-api-and-sessions.md) | Sync FastAPI, sessions in Postgres with optimistic locking | Proposed |
| [0016](0016-angular-widget.md) | Chat widget in Angular | Proposed |
| [0017](0017-observability.md) | OpenTelemetry traces with GenAI semantic conventions | Proposed |
| [0018](0018-store-profile.md) | Store-agnostic assistant driven by a validated store profile | Proposed |
| [0019](0019-generic-catalog.md) | A catalog model that fits real shops' data | Proposed |
| [0020](0020-shopify-import.md) | Platform adapters, starting with a Shopify catalog importer | Proposed |
| [0021](0021-policy-consistency-check.md) | Check policy texts against the profile before going live | Proposed |
| [0022](0022-hosted-demo.md) | A free hosted demo behind a login and a spending cap | Accepted |

Template: [`template.md`](template.md).
