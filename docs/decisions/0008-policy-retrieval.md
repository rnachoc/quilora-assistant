# 0008. Policy retrieval: FTS first, vector and hybrid measured against it

- **Status:** Proposed
- **Date:** 2026-10-09
- **Author:** Ignacio Rodríguez Caro

## Context

The assistant must answer policy questions from Quilora's own text and cite the section.
That is retrieval-augmented generation (RAG): retrieve the relevant sections, then let the
model answer from them. The corpus is small (8 documents, 42 sections) and in English;
customers write in Spanish and English, with their own words.

## Options

1. **Put all policies in the system prompt**: zero retrieval errors, simple; but every turn
   pays for ~3k extra tokens (mitigated by caching), it does not scale with the corpus and
   it does not teach retrieval.
2. **Postgres full-text search (FTS)**: exact, cheap (<1 ms), explainable; misses synonyms
   and other languages.
3. **Vector search with pgvector**: matches meaning and cross-language; needs an embedding
   model, can return confident but wrong neighbours.
4. **Hybrid (Reciprocal Rank Fusion of 2 and 3)**: robust when neither signal dominates.

## Decision

Implement 2, 3 and 4 behind one function and a config flag (`POLICY_SEARCH_BACKEND`), and
choose with numbers from `python -m quilora.search.compare` on 36 labelled queries in three
groups (English keywords, English paraphrases, Spanish).

Default: **FTS**, combined with a tool description that asks the model to rewrite the
question in English with key terms. FTS measured Hit@3 = 1.00 on keyword-style queries,
0.58 on paraphrases and 0.08 on raw Spanish. Because the model performs the rewrite, the
query that reaches the tool usually looks like the keyword group. The default should move to
`hybrid` if the vector numbers (pending, see `docs/results/retrieval.md`) improve the
paraphrase and Spanish groups without hurting keywords.

## Consequences

- Retrieval quality is a measured property with a regression test set, not an impression.
- Query rewriting is delegated to the model through the tool description; the agent-level
  evals check that policy answers cite the right section.
- Option 1 remains a valid simplification for a corpus this small and is mentioned in the
  interview notes as the honest baseline.
