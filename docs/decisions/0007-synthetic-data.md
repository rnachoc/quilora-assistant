# 0007. Fictional store, synthetic data, English catalog

- **Status:** Proposed
- **Date:** 2026-10-09
- **Author:** Ignacio Rodríguez Caro

## Context

The repository is public. No real store, brand or customer data may appear. The assistant
must answer customers in Spanish and English.

## Options for the data

1. **Hand-written fixtures**: realistic but slow to produce and hard to change.
2. **LLM-generated data**: fast, but non-reproducible and may leak real brand names.
3. **Seeded deterministic generator (Python)**: same output on every run, reviewable,
   easy to regenerate after a schema change.

## Options for the catalog language

1. **English**: consistent with the codebase; the model translates search terms
   ("vestido de lino" becomes "linen dress") before calling the tool.
2. **Spanish**: closer to a Spanish shop, but mixed languages inside the repo.
3. **Both**: doubles the data and the search complexity.

## Decision

- The store is **Quilora** (invented name), domain `quilora.example` (the `.example` TLD is
  reserved by RFC 2606), customer emails use `example.com`.
- A seeded generator (`data/generate.py`) produces products, size charts and orders.
  Policies are hand-written Markdown in `data/policies/`.
- Catalog and policies are in **English**. Tool descriptions instruct the model to query in
  English; the vector search experiment (phase 4) measures how much multilingual
  embeddings help when the query arrives in Spanish.

## Consequences

- Evaluation cases can reference exact product names and prices because the data is
  deterministic.
- A reference date (`STORE_TODAY`) makes return-window logic reproducible.
