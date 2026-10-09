# Running the assistant for your own store

_Author: Ignacio Rodríguez Caro_

The code is store-agnostic. A shop is a directory:

```
my_store/
  store.yaml        profile: identity, languages, shipping, returns, promotions...
  policies/         the shop's policies as Markdown or plain text
  generated/        catalog (and, if you have them, size charts, customers, orders) as JSON
```

## 1. Write the profile

Copy `data/store.yaml` (the documented demo profile) and adapt it. The fields that matter
most:

| Field | Why it matters |
|-------|----------------|
| `catalog.language`, `catalog.search_config` | Language of product and policy texts; Postgres text-search config (`spanish`, `english`, `french`...) |
| `shipping.processing_business_days`, `cutoff_hour`, `holidays` | Delivery estimates |
| `shipping.zones` | Destinations (`ES`, `ES-CN`, `EU`, `*`), transit days, cost, free-shipping threshold |
| `returns` | Window, who pays return shipping, method (prepaid label, address on request, drop-off), exchanges, refund days |
| `order_changes` | Order statuses in which cancellation or address change can still be requested |
| `tracking_url_template` | Customer tracking page with `{tracking_code}` |
| `promotions` | The only discount codes the assistant may ever share |
| `catalog.fallback_size_charts` | General size guide per department for products without one |

## 2. Add the policies

Put each policy in `policies/` as Markdown or text. Numbered sections (`## 1. Title`) are
cited with their numbers; other formats are split automatically. Add
`<!-- doc_id: RET -->` to choose stable IDs and reference them from the profile
(`policy_ref`, `returns.policy_refs`).

## 3. Import the catalog (Shopify)

```bash
curl -s "https://YOUR-SHOP/products.json?limit=250&page=1" > products.json
python -m quilora.importers.shopify products.json --store-dir my_store \
    --domain YOUR-SHOP --strip-title-prefix
```

(The public feed is paginated: repeat with `page=2`, `3`... and merge, or use an Admin API
export.) Products, variants, availability, prices, previous prices and tags are imported;
material only when written as percentages. Nothing is invented.

## 4. Check before going live

```bash
STORE_DIR=my_store make check-store
```

Fix every warning and contradiction in the policies or the profile. The assistant cannot
be more consistent than the texts it cites.

## 5. Load and run

```bash
STORE_DIR=my_store make seed
STORE_DIR=my_store make chat     # or make api / docker compose with STORE_DIR mounted
```

## 6. Evaluate with your own cases

The bundled 83 cases test the demo shop's data. For your shop, copy `evals/cases/`, rewrite
the cases with your products, orders and rules, and run `make eval` against them. Never
put real customer data in a public repository.

## Not covered yet

- Orders: there is no public order feed. Load orders from your platform's admin API into
  `generated/orders.json` (same format as the demo) or implement an orders adapter.
- Size charts published as images cannot be imported; write them into
  `generated/size_charts.json`.
