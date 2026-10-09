-- Author: Ignacio Rodríguez Caro
-- 005: make the catalog fit any online fashion shop (e.g. a Shopify export).
--  * free-form IDs and categories (shops name things their own way)
--  * tags and collections searchable, sale prices (compare-at), product URL
--  * material, care, fit and size chart become optional (many shops do not publish them)
--  * stock counts optional: public catalog feeds often only say "available" or not
--  * full-text search in the catalog's own language (column, not a hard-coded 'english')

-- array_to_string is only STABLE in general; for text[] it is safe to declare IMMUTABLE so it
-- can be used inside generated columns.
CREATE OR REPLACE FUNCTION immutable_join(text[]) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ SELECT coalesce(array_to_string($1, ' '), '') $$;

ALTER TABLE products DROP CONSTRAINT IF EXISTS products_category_check;
ALTER TABLE products ALTER COLUMN material DROP NOT NULL;
ALTER TABLE products ALTER COLUMN care DROP NOT NULL;
ALTER TABLE products ALTER COLUMN fit DROP NOT NULL;
ALTER TABLE products ALTER COLUMN size_chart_id DROP NOT NULL;
ALTER TABLE products
    ADD COLUMN tags TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN collections TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN compare_at_price_eur NUMERIC(8, 2) CHECK (compare_at_price_eur > 0),
    ADD COLUMN url TEXT,
    ADD COLUMN model_info TEXT,                       -- e.g. "Model is 175 cm and wears S"
    ADD COLUMN search_config REGCONFIG NOT NULL DEFAULT 'english';

ALTER TABLE products DROP COLUMN search_tsv;
ALTER TABLE products ADD COLUMN search_tsv TSVECTOR GENERATED ALWAYS AS (
    setweight(to_tsvector(search_config, name), 'A') ||
    setweight(to_tsvector(search_config, category || ' ' || gender || ' ' ||
              coalesce(material, '') || ' ' || immutable_join(tags) || ' ' ||
              immutable_join(collections)), 'B') ||
    setweight(to_tsvector(search_config, description), 'C')
) STORED;
CREATE INDEX products_search_idx ON products USING GIN (search_tsv);
CREATE INDEX products_tags_idx ON products USING GIN (tags);

ALTER TABLE product_variants ALTER COLUMN stock DROP NOT NULL;
ALTER TABLE product_variants ADD COLUMN available BOOLEAN NOT NULL DEFAULT true;

ALTER TABLE policy_chunks ADD COLUMN search_config REGCONFIG NOT NULL DEFAULT 'english';
ALTER TABLE policy_chunks DROP COLUMN search_tsv;
ALTER TABLE policy_chunks ADD COLUMN search_tsv TSVECTOR GENERATED ALWAYS AS (
    setweight(to_tsvector(search_config, doc_title || ' ' || section_title), 'A') ||
    setweight(to_tsvector(search_config, content), 'B')
) STORED;
CREATE INDEX policy_chunks_search_idx ON policy_chunks USING GIN (search_tsv);

-- Free-form order statuses from other platforms map onto ours; shipments may be split.
ALTER TABLE orders ADD COLUMN tracking_url TEXT;
