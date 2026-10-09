# 0016. Chat widget in Angular

- **Status:** Proposed
- **Date:** 2026-10-09

## Context

The assistant needs a minimal chat UI for demos. Angular with TypeScript is my front-end
stack; the target company also uses TypeScript.

## Options

1. **Plain HTML + JavaScript served by FastAPI**: smallest; nothing to build; not
   representative of a real front end.
2. **React**: the most common choice for chat widgets; not my day-to-day framework.
3. **Angular 22 (standalone components, signals, zoneless)**: my stack, typed contract with
   the API, production build served by nginx.

## Decision

Option 3, deliberately minimal: one storefront component, one widget component, one
service, typed models mirroring the API. No router, no forms module, no UI library.

## Consequences

- Model output is rendered with interpolation only (never `innerHTML`), so a malicious or
  injected reply cannot execute script in the customer's browser.
- A "Details" toggle shows tools, latency and cost per turn: useful for demos and for
  explaining the system; it would be hidden in production.
- Next step: render the return summary with Confirm/Cancel buttons (ADR 0010, option 4).
