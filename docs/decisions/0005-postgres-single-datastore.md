# 0005. PostgreSQL as the single datastore

- **Status:** Proposed
- **Date:** 2026-10-09
- **Author:** Ignacio Rodríguez Caro

## Context

We need to store the catalog, stock, orders, return requests, support tickets, policy text
(for search), embeddings and chat sessions.

## Options

1. **PostgreSQL for everything** (relational data, full-text search, `pgvector`, JSONB sessions)
   - Pros: one system to run, back up and secure; transactions across return requests and
     audit log; I know it well; FTS and vectors side by side make the retrieval comparison
     fair (same data, same database).
   - Cons: not a dedicated search engine (no BM25 out of the box, fewer relevance knobs);
     vector search at very large scale is better served elsewhere.
2. **PostgreSQL + Elasticsearch/OpenSearch + Redis**
   - Pros: best-in-class search, fast session cache.
   - Cons: three systems for ~100 products and ~10 policy pages; operational cost with no
     measurable benefit at this size.
3. **Dedicated vector DB (Qdrant, Pinecone) + PostgreSQL**
   - Pros: purpose-built ANN indexes and filtering.
   - Cons: same over-engineering argument; data synchronisation problem.

## Decision

Option 1. Start with one database and let the measurements decide whether search deserves a
dedicated engine.

## Consequences

- Policy search can be switched between FTS, vector and hybrid with a config flag.
- Documented scale-up path: OpenSearch for search and Redis for sessions if traffic or
  catalog size grow by orders of magnitude.
