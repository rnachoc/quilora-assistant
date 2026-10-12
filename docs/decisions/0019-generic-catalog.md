# 0019. A catalog model that fits real shops' data

- **Status:** Proposed
- **Date:** 2026-10-09
- **Author:** Ignacio Rodríguez Caro

## Context

Real catalogs, such as a typical Shopify public feed, differ from the synthetic one:
free-form IDs (handles), categories named by the shop, tags and collections that carry
meaning ("new in", "occasion wear"), sizes from 2XS to 4XL, previous prices on sale items, no unit
counts in public feeds (only "available"), and often no material, care instructions, fit
or size chart at all.

## Options

1. **Force every shop into the synthetic schema** (fixed categories, required fields):
   imports fail or get filled with invented values.
2. **Store each shop's raw JSON and let the model read it**: flexible, but no validation,
   no filters, and the model starts guessing missing details.
3. **Generalise the schema**: optional details, free categories, tags and collections in
   full-text search, availability with or without counts, sale prices, size normalisation,
   text search in the catalog's own language.

## Decision

Option 3 (migrations 005 and 006):

- Missing details are `NULL`, and `get_product` returns `not_published` with a hint to say
  so; the prompt forbids inferring fabric or fit from names, tags or descriptions.
- Discounts are computed by code from `compare_at_price` (`discount_pct`); the model may
  only mention a previous price when the tool returns one (relevant for price-indication
  rules in EU consumer law).
- Size labels are compared through `canonical_size` (XXL = 2XL, "Talla única" = ONE SIZE).
- Products without a size chart use the store's general guide per department, reported
  as low confidence; with neither, the tool says no size information exists.
- Full-text search uses each row's `search_config` (e.g. `spanish`), set from the profile.

## Consequences

- A Shopify feed loads without inventing data; the assistant is honest about gaps.
- Category names are no longer an enum in the tool schema; when a search finds nothing, the
  tool returns the shop's known categories so the model can retry.
