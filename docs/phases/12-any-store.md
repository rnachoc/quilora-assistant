# Phase 12: From one demo shop to any online fashion store

_Author: Ignacio Rodríguez Caro_

## Why

Reviewing a real Shopify dropshipping fashion store (October 2026) showed the gap between
a synthetic demo and production data:

| Observed in the real shop | What the first version assumed |
|---------------------------|--------------------------------|
| Handles as IDs, categories named by the shop, rich tags | `QL-ABC-123` IDs and a fixed category list |
| Sizes 2XS to 4XL | XS to XL |
| Previous prices on most products ("-50%") | No sale prices |
| Public feed with available/unavailable, no unit counts | Unit counts per variant |
| No material, care or size chart in product pages | Always present |
| Long, ranged delivery times by region; no weekend processing | A carrier ETA on every order |
| Returns to a warehouse abroad, address sent by email, paid by the customer, no exchanges | Free prepaid label |
| Orders cannot be cancelled once placed | Cancellation while processing |
| Tracking through a tracking app page | No tracking link |
| Policies contradicting themselves (30 vs 14 days; two processing times) | One consistent policy set |

None of these are specific to that shop; they are common in small fashion e-commerce.

## Concept

Separate **what is the same for every shop** (the agent loop, tool contracts, security
rules, evaluation) from **what each shop decides** (the store profile), and make the
decision-driving numbers structured data rather than prose. The model reads policies to
*cite* them; the code computes answers from the profile.

## What was built

| Area | Change |
|------|--------|
| `store/profile.py`, `data/store.yaml` | Validated store profile; legal warnings (EU withdrawal) |
| `domain/delivery.py`, `tools/store_info.py` | `estimate_delivery` (business days, cut-off, holidays, zones) and `get_active_promotions` |
| `domain/sizes.py` | Size label normalisation and natural ordering |
| `tools/catalog.py`, migrations 005-006 | Free IDs and categories, tags and collections, sale prices with code-computed discounts, optional details with `not_published`, availability without counts, catalog-language search, store size-guide fallback |
| `tools/orders.py` | Expected window for unshipped orders, tracking link, `customer_can_request` |
| `tools/returns.py`, `tools/handoff.py` | Return terms, refund timing and support hours from the profile |
| `agent/prompts/*.md`, tool descriptions | Templates filled from the profile (no shop name in code) |
| `search/chunking.py` | Policies in any Markdown or text layout; long sections split |
| `importers/shopify.py` | Shopify products feed importer |
| `store/consistency.py` | Policy-versus-profile contradiction check (`make check-store`) |
| API and widget | `GET /api/store`; the widget shows the configured shop |
| Tests | A second fictional shop in Spanish (own schema, Spanish stemming, contradictory policies) runs end to end |
| Evals | 11 new cases (delivery, sales, unpublished details, size guide fallback, promotions, cancellations, tracking) |

## How to verify

```bash
make test                                   # includes tests/test_generic_store.py
make check-store                            # demo shop: OK
python -m quilora.store.consistency --store-dir tests/fixtures/spanish_store
```

See [adding-a-store.md](../adding-a-store.md) to run it for a real shop, and ADRs
[0018](../decisions/0018-store-profile.md) to [0021](../decisions/0021-policy-consistency-check.md).
