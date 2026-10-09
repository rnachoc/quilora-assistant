"""Compute and store embeddings for all policy chunks.

    python -m quilora.search.embed

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import psycopg

from quilora.config import load_settings
from quilora.db import migrate
from quilora.search.embeddings import Embedder, FastEmbedEmbedder, to_pgvector


def embed_policies(conn: psycopg.Connection, embedder: Embedder) -> int:
    """Compute and store an embedding for every policy chunk."""
    rows = conn.execute(
        "SELECT id, doc_title, section_title, content FROM policy_chunks ORDER BY id"
    ).fetchall()
    # Title and section heading carry a lot of meaning for short chunks: embed them too.
    texts = [f"{r[1]}. {r[2]}. {r[3]}" for r in rows]
    vectors = embedder.embed_documents(texts)
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE policy_chunks SET embedding = %s::vector, embedding_model = %s WHERE id = %s",
            [(to_pgvector(v), embedder.model_name, r[0]) for r, v in zip(rows, vectors,
                                                                          strict=True)],
        )
    return len(rows)


def main() -> None:
    """Command-line entry point: embed all policies with the configured model."""
    settings = load_settings()
    embedder = FastEmbedEmbedder(settings.embedding_model)
    with psycopg.connect(settings.database_url) as conn:
        migrate(conn)
        count = embed_policies(conn, embedder)
    print(f"Embedded {count} policy chunks with {embedder.model_name} ({embedder.dimensions} d)")


if __name__ == "__main__":
    main()
