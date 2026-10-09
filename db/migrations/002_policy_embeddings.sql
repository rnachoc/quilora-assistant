-- 002: semantic search over policy chunks with pgvector.
-- Requires the pgvector extension (bundled in the pgvector/pgvector Docker image).

CREATE EXTENSION IF NOT EXISTS vector;

-- 384 dimensions = sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2.
-- Changing EMBEDDING_MODEL to a model with another dimension requires a new migration.
ALTER TABLE policy_chunks ADD COLUMN embedding vector(384);
ALTER TABLE policy_chunks ADD COLUMN embedding_model TEXT;

-- No ANN index on purpose: with ~40 chunks an exact scan is faster than HNSW and returns
-- exact results. Add `USING hnsw (embedding vector_cosine_ops)` when the corpus reaches
-- tens of thousands of chunks, and measure recall against the exact scan when you do.
