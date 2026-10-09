# Phase 1: Synthetic data

_Author: Ignacio Rodríguez Caro_

## Concept

An agent is only as good as the data its tools return. Before touching the model we need a
store: products with variants (colour × size) and stock, size charts, orders in every
lifecycle state, and policies written as text. Because the repository is public, all of it
is synthetic.

Two properties matter more than realism:

1. **Determinism.** A seeded generator produces byte-identical files on every run, so
   evaluation cases can assert exact product names, prices and stock levels.
2. **Planted scenarios.** The generator pins the facts that tests depend on: linen dresses
   on both sides of 60 EUR, a size M sold out in one colour and available in another, order
   1043 with a T-shirt inside the return window, an order outside it, a final-sale item, a
   delayed parcel, and an order whose customer-provided delivery note contains a
   prompt-injection attempt.

## What was built

| Path | Content |
|------|---------|
| `data/generate.py` | Seeded generator → `data/generated/*.json` |
| `data/generated/` | 81 products, 1003 variants, 8 size charts, 20 customers, 30 orders |
| `data/policies/*.md` | 8 policy documents, 42 numbered sections |
| `db/migrations/001_*.sql` | Schema with constraints and generated `tsvector` columns |
| `src/quilora/seed.py` | Migration + load (`make seed`) |
| `src/quilora/search/chunking.py` | Splits policies into citable sections (`RET-1`, `SHP-2`, ...) |

## Design notes

- **Constraints in the schema** (`CHECK`, `UNIQUE`, foreign keys) catch generator bugs
  early; the database is the last line of defence for data quality.
- **Stock lives on the variant** (`product_variants`), because "is M in black available?"
  is a question about one SKU, not a product.
- **`delivery_notes` is marked UNTRUSTED** in the schema comment: it is customer input that
  will later flow into the model's context.
- **Policies are chunked by section**, which gives each search hit a stable ID to cite and
  keeps chunks under ~80 words (small embedding models truncate long inputs; see phase 4).
- **A fixed store clock** (`STORE_TODAY=2026-10-01`) makes "is this order still returnable?"
  reproducible.

## How to verify

```bash
make data && git diff --exit-code data/generated   # deterministic
make seed                                          # loads Postgres
make test                                          # tests/test_data.py
```
