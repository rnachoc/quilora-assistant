# 0009. Local multilingual embedding model through fastembed

- **Status:** Proposed
- **Date:** 2026-10-09

## Context

Vector search needs an embedding model. Anthropic's API does not provide embeddings; its
documentation points to third-party providers such as Voyage AI. Queries arrive in Spanish
and English while policies are in English.

## Options

1. **Hosted API (Voyage AI or similar)**: high quality, no local resources; a second API
   key, per-call cost, network latency, and customer text leaves our infrastructure.
2. **Local model with sentence-transformers (PyTorch)**: flexible; installs PyTorch
   (gigabytes), slow container builds.
3. **Local model with fastembed (ONNX runtime)**: small install, CPU-friendly, curated list
   of models including multilingual ones; less flexible than PyTorch.

## Decision

Option 3 with `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
(384 dimensions, ~0.2 GB, about 50 languages), listed by `fastembed` 0.9.0 as supported.
It is an optional extra (`pip install -e '.[embeddings]'`) so the FTS path has no
machine-learning dependency at all.

## Consequences

- fastembed reports a 128-token input limit for this model, so policy sections are kept
  under ~80 words (enforced by a test).
- The vector column is `vector(384)`; changing model means a new migration and re-embedding.
- `paraphrase-multilingual-mpnet-base-v2` (768 d, 512 tokens) is the next candidate if
  recall is not good enough; the comparison script makes that a measurable change.
- Tests use a deterministic hashing embedder, so CI never downloads a model.
