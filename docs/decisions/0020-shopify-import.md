# 0020. Platform adapters, starting with a Shopify catalog importer

- **Status:** Proposed
- **Date:** 2026-10-09
- **Author:** Ignacio Rodríguez Caro

## Context

To serve a real shop, its catalog must get into the assistant's database. Shopify is the
most common platform for small fashion brands and dropshipping shops.

## Options

1. **Live calls to the Shopify Admin API from the tools**: always fresh; needs credentials,
   rate-limit handling and a network dependency on every turn.
2. **Periodic import from the public `products.json` feed or an Admin export** into
   Postgres: simple, testable offline, the same tools work for every platform.
3. **A generic CSV format the shop fills in by hand**: universal but laborious.

## Decision

Option 2 for the catalog (`python -m quilora.importers.shopify`), as the first adapter. It
maps handles, titles (optionally without a "BRAND | " prefix), product types, tags,
colour and size options recognised by name in several languages, variant availability,
prices and previous prices, and extracts a composition only when it is written as
percentages. Everything else stays empty.

## Consequences

- Catalog freshness depends on how often the import runs (a scheduled job; stock in the
  public feed is only available / not available).
- Orders are not public. A real deployment needs an orders adapter (Shopify Admin API
  `orders` with the customer's email check kept in our tool), listed as the next step.
- Other platforms (WooCommerce, PrestaShop) are new adapters with the same output format.
