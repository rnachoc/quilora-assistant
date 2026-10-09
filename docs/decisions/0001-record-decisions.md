# 0001. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-10-09

## Context

This project is a learning vehicle and a portfolio piece. Every non-trivial choice must be
explainable and defensible later, by someone who was not in the room (including future me).

## Options

1. **No formal record**: fastest, but the reasoning is lost.
2. **Long design document**: complete, but goes stale and nobody re-reads it.
3. **Short ADRs, one per decision**: small, append-only, easy to review in a pull request.

## Decision

Option 3. ADRs live in `docs/decisions/`, are numbered, and follow `template.md`.

## Consequences

- Each decision has a home; superseding a decision means writing a new ADR, not editing history.
- Small overhead per decision (10 minutes).
