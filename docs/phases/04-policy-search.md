# Phase 4: Policy search (FTS vs pgvector)

_Author: Ignacio Rodríguez Caro_

## Concept

**RAG** (retrieval-augmented generation) means: find the passages that answer the
question, put them in the model's context, and have the model answer *from them*. The
answer quality is capped by retrieval quality: if the right section is not retrieved, the
model either says it does not know (good) or improvises (bad).

Two ways to retrieve:

- **Full-text search (FTS)**: Postgres turns text into normalised word stems
  (`tsvector`, "returns" → "return") and matches query stems. Fast, exact, explainable.
  Blind to synonyms ("money back" vs "refund") and to other languages.
- **Vector search**: an embedding model maps text to a vector so that texts with similar
  meaning end up close; we store vectors in Postgres with `pgvector` and order by cosine
  distance. Handles paraphrases and Spanish → English. Less explainable, and it always
  returns *something*, even when nothing is relevant.
- **Hybrid**: run both and merge the rankings with Reciprocal Rank Fusion
  (`score = Σ 1/(60 + rank)`), which needs no score calibration between the two systems.

## What was built

| File | Responsibility |
|------|----------------|
| `db/migrations/002_policy_embeddings.sql` | `vector(384)` column (no ANN index, on purpose) |
| `search/policies.py` | `search_fts`, `search_vector`, `search_hybrid`, fallback to FTS |
| `search/embeddings.py` | `FastEmbedEmbedder` (local ONNX) and a hashing embedder for tests |
| `search/embed.py` | `make embed`: embeds title + section + text of every chunk |
| `search/compare.py` | `make compare-search`: Hit@1, Hit@3, MRR, latency per group |
| `tools/policies.py` | `search_policies` tool with citations and "do not guess" hints |
| `evals/retrieval/queries.yaml` | 36 labelled queries in three groups |

## Results so far

FTS (measured, see [`docs/results/retrieval.md`](../results/retrieval.md)):

| Group | Hit@1 | Hit@3 | MRR |
|-------|-------|-------|-----|
| English keywords | 1.00 | 1.00 | 1.00 |
| English paraphrases | 0.33 | 0.58 | 0.43 |
| Spanish | 0.08 | 0.08 | 0.08 |

Vector and hybrid: **pending**. The embedding model could not be downloaded in the
environment where this was built. Run:

```bash
pip install -e '.[embeddings]'
make embed && make compare-search
```

## How to read the numbers

1. FTS is perfect when the query uses the policy's words, and collapses on Spanish.
2. In the real agent, the model rewrites the question in English with key terms before
   calling the tool (the tool description asks for it), so production queries look more
   like the keyword group. That is a cheap and explainable alternative to embeddings.
3. Vector search should lift the paraphrase and Spanish groups. If hybrid keeps keyword
   performance and lifts the rest, it becomes the default (ADR 0008).
4. 36 queries is a small sample: a difference of one query is ~3 points. Treat small
   deltas as noise.
