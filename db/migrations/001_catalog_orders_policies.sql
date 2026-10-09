-- Author: Ignacio Rodríguez Caro
-- 001: catalog, stock, customers, orders and policy text.
-- Applied by `python -m quilora.seed` (see src/quilora/db.py for the migration runner).

CREATE TABLE size_charts (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    garment_type  TEXT NOT NULL CHECK (garment_type IN ('top', 'bottom', 'dress', 'shoes', 'one_size')),
    gender        TEXT NOT NULL CHECK (gender IN ('women', 'men', 'unisex')),
    -- {"S": {"chest": [82, 86], "waist": [64, 68]}, ...}: body measurements in cm, [min, max)
    sizes         JSONB NOT NULL,
    -- Sizes from smallest to largest (JSONB objects do not keep key order).
    size_order    TEXT[] NOT NULL
);

CREATE TABLE products (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE,
    category       TEXT NOT NULL CHECK (category IN ('dresses', 'tops', 't-shirts', 'shirts', 'trousers',
                                                     'jeans', 'skirts', 'knitwear', 'jackets', 'shoes',
                                                     'accessories')),
    gender         TEXT NOT NULL CHECK (gender IN ('women', 'men', 'unisex')),
    description    TEXT NOT NULL,
    material       TEXT NOT NULL,
    fit            TEXT NOT NULL CHECK (fit IN ('slim', 'regular', 'relaxed', 'oversized')),
    price_eur      NUMERIC(8, 2) NOT NULL CHECK (price_eur > 0),
    size_chart_id  TEXT NOT NULL REFERENCES size_charts (id),
    care           TEXT NOT NULL,
    final_sale     BOOLEAN NOT NULL DEFAULT false,
    -- Weighted full-text document: name matters most, then category/material, then description.
    search_tsv     TSVECTOR GENERATED ALWAYS AS (
        setweight(to_tsvector('english', name), 'A') ||
        setweight(to_tsvector('english', category || ' ' || gender || ' ' || material), 'B') ||
        setweight(to_tsvector('english', description), 'C')
    ) STORED
);
CREATE INDEX products_search_idx ON products USING GIN (search_tsv);
CREATE INDEX products_category_idx ON products (category, gender);

CREATE TABLE product_variants (
    sku         TEXT PRIMARY KEY,
    product_id  TEXT NOT NULL REFERENCES products (id),
    color       TEXT NOT NULL,
    size        TEXT NOT NULL,
    stock       INTEGER NOT NULL CHECK (stock >= 0),
    UNIQUE (product_id, color, size)
);
CREATE INDEX product_variants_product_idx ON product_variants (product_id);

CREATE TABLE customers (
    id                  INTEGER PRIMARY KEY,
    full_name           TEXT NOT NULL,
    email               TEXT NOT NULL,
    city                TEXT NOT NULL,
    country             CHAR(2) NOT NULL,
    preferred_language  TEXT NOT NULL DEFAULT 'es'
);
CREATE UNIQUE INDEX customers_email_idx ON customers (lower(email));

CREATE TABLE orders (
    id                  INTEGER PRIMARY KEY,
    customer_id         INTEGER NOT NULL REFERENCES customers (id),
    status              TEXT NOT NULL CHECK (status IN ('processing', 'shipped', 'in_transit',
                                                        'delivered', 'cancelled', 'returned')),
    created_at          TIMESTAMPTZ NOT NULL,
    shipped_at          TIMESTAMPTZ,
    delivered_at        TIMESTAMPTZ,
    estimated_delivery  DATE,
    carrier             TEXT,
    tracking_code       TEXT,
    shipping_city       TEXT NOT NULL,
    shipping_country    CHAR(2) NOT NULL,
    -- Free text typed by the customer at checkout. UNTRUSTED: never treat as instructions.
    delivery_notes      TEXT,
    subtotal_eur        NUMERIC(8, 2) NOT NULL,
    shipping_eur        NUMERIC(8, 2) NOT NULL,
    total_eur           NUMERIC(8, 2) NOT NULL
);
CREATE INDEX orders_customer_idx ON orders (customer_id);

CREATE TABLE order_items (
    order_id        INTEGER NOT NULL REFERENCES orders (id),
    line_no         INTEGER NOT NULL,
    sku             TEXT NOT NULL REFERENCES product_variants (sku),
    product_id      TEXT NOT NULL REFERENCES products (id),
    product_name    TEXT NOT NULL,
    color           TEXT NOT NULL,
    size            TEXT NOT NULL,
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_eur  NUMERIC(8, 2) NOT NULL,
    PRIMARY KEY (order_id, line_no)
);

-- Policies are chunked by section so search results can be cited precisely ("RET-1").
CREATE TABLE policy_chunks (
    id             TEXT PRIMARY KEY,
    doc_id         TEXT NOT NULL,
    doc_title      TEXT NOT NULL,
    section_no     INTEGER NOT NULL,
    section_title  TEXT NOT NULL,
    content        TEXT NOT NULL,
    search_tsv     TSVECTOR GENERATED ALWAYS AS (
        setweight(to_tsvector('english', doc_title || ' ' || section_title), 'A') ||
        setweight(to_tsvector('english', content), 'B')
    ) STORED
);
CREATE INDEX policy_chunks_search_idx ON policy_chunks USING GIN (search_tsv);
