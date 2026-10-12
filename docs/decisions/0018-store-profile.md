# 0018. Store-agnostic assistant driven by a validated store profile

- **Status:** Proposed
- **Date:** 2026-10-09
- **Author:** Ignacio Rodríguez Caro

## Context

The first version was written for one fictional shop: its name, shipping zones, return
terms and support hours were spread across the prompt, tool texts and constants. Small
online fashion shops differ in exactly those things (languages, processing and transit
times, who pays return shipping and where returns are sent, whether orders can be
cancelled, tracking pages, public promotions), and their policy texts often contradict
themselves.

## Options

1. **Keep one shop, edit the code per client**: fast once, unmaintainable after the second
   client.
2. **Put everything in the policy texts and let the model read them**: no new structure,
   but numbers that drive decisions (return window, delivery dates) would depend on which
   section retrieval returns, and contradictory texts produce contradictory answers.
3. **A validated store profile (YAML + Pydantic) for decision-driving facts, policies for
   citation**, with prompts and tool descriptions as templates.

## Decision

Option 3. `STORE_DIR/store.yaml` holds identity, languages, catalog language, contact and
support hours, processing days and cut-off hour, holidays, shipping zones (with region
codes, transit days, costs and free-shipping thresholds), return terms, which order
statuses allow cancellation or address changes, a tracking URL template and public
promotions. Code computes from it; texts cite the policies.

New tools built on it: `estimate_delivery` (business-day arithmetic in `domain/delivery.py`)
and `get_active_promotions` (the only source of shareable codes). The order view adds the
expected window for orders not shipped yet, a tracking link and `customer_can_request`
(cancellation, address change).

## Consequences

- Onboarding a shop is configuration (`docs/adding-a-store.md`), not code.
- The profile validator flags legal risks (e.g. a return window shorter than the EU 14-day
  withdrawal period, or "orders can never be cancelled" without explaining withdrawal).
- One process serves one shop. Multi-tenant hosting would load one profile per tenant and
  use one database schema per shop (`Database(search_path=...)` already supports it).
