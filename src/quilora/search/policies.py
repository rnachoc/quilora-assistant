"""Policy retrieval: full-text (FTS), vector (pgvector) and hybrid (RRF).

* FTS: Postgres `tsvector` with the English stemmer. Exact words, cheap, explainable;
  misses synonyms and other languages.
* Vector: cosine distance between multilingual embeddings. Matches meaning and Spanish
  queries; can return confidently wrong neighbours and is harder to explain.
* Hybrid: Reciprocal Rank Fusion of both lists, score = sum(1 / (K + rank)). Robust
  default when neither signal dominates; no score calibration needed.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import psycopg

from quilora.search.embeddings import Embedder, to_pgvector

RRF_K = 60
CANDIDATES = 10


@dataclass(frozen=True)
class PolicyHit:
    """A retrieved policy section with its relevance score."""
    chunk_id: str
    doc_title: str
    section_no: int
    section_title: str
    content: str
    score: float

    @property
    def citation(self) -> str:
        """Human-readable citation for the assistant to quote."""
        return f"{self.doc_title} §{self.section_no} ({self.section_title})"


def _hit(row: dict, score: float) -> PolicyHit:
    return PolicyHit(row["id"], row["doc_title"], row["section_no"], row["section_title"],
                     row["content"], round(float(score), 4))


def _or_terms(query: str) -> str:
    """Turn free text into an OR tsquery of its words, so partial matches still rank."""
    words = [w for w in re.findall(r"[^\W\d_]+", query.lower()) if len(w) > 1]
    return " | ".join(words)


def search_fts(conn: psycopg.Connection, query: str, limit: int) -> list[PolicyHit]:
    """Full-text search with the English stemmer, ranked by cover density."""
    terms = _or_terms(query)
    if not terms:
        return []
    # OR semantics + cover-density ranking: chunks matching more (and closer) terms win.
    rows = conn.execute(
        # Each chunk is parsed with its own text-search language (set from the store profile).
        "SELECT id, doc_title, section_no, section_title, content,"
        "       ts_rank_cd(search_tsv, q) AS score"
        "  FROM policy_chunks, LATERAL to_tsquery(search_config, %s) AS q"
        " WHERE search_tsv @@ q ORDER BY score DESC, id LIMIT %s",
        (terms, limit),
    ).fetchall()
    return [_hit(r, r["score"]) for r in rows]


def search_vector(conn: psycopg.Connection, query: str, limit: int,
                  embedder: Embedder) -> list[PolicyHit]:
    """Semantic search: cosine distance between the query embedding and chunk embeddings."""
    vector = to_pgvector(embedder.embed_query(query))
    rows = conn.execute(
        "SELECT id, doc_title, section_no, section_title, content,"
        "       1 - (embedding <=> %s::vector) AS score"
        "  FROM policy_chunks WHERE embedding IS NOT NULL"
        " ORDER BY embedding <=> %s::vector LIMIT %s",
        (vector, vector, limit),
    ).fetchall()
    return [_hit(r, r["score"]) for r in rows]


def search_hybrid(conn: psycopg.Connection, query: str, limit: int,
                  embedder: Embedder) -> list[PolicyHit]:
    """Merge FTS and vector rankings with Reciprocal Rank Fusion."""
    fts = search_fts(conn, query, CANDIDATES)
    vec = search_vector(conn, query, CANDIDATES, embedder)
    scores: dict[str, float] = {}
    hits: dict[str, PolicyHit] = {}
    for ranked in (fts, vec):
        for rank, hit in enumerate(ranked, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            hits.setdefault(hit.chunk_id, hit)
    best = sorted(scores, key=lambda cid: (-scores[cid], cid))[:limit]
    return [PolicyHit(**{**hits[cid].__dict__, "score": round(scores[cid], 5)}) for cid in best]


def embeddings_available(conn: psycopg.Connection) -> bool:
    """True if the embedding column exists and has been filled."""
    row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name ="
        " 'policy_chunks' AND column_name = 'embedding') AS has_col"
    ).fetchone()
    if not row["has_col"]:
        return False
    return conn.execute(
        "SELECT count(*) > 0 AS ok FROM policy_chunks WHERE embedding IS NOT NULL"
    ).fetchone()["ok"]


def search(conn: psycopg.Connection, query: str, *, backend: str, limit: int = 3,
           embedder: Embedder | None = None) -> tuple[list[PolicyHit], str]:
    """Run the configured backend, falling back to FTS if vectors are unavailable."""
    if backend in {"vector", "hybrid"} and embedder is not None and embeddings_available(conn):
        fn = search_vector if backend == "vector" else search_hybrid
        return fn(conn, query, limit, embedder), backend
    return search_fts(conn, query, limit), "fts"
