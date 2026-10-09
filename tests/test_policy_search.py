"""Phase 4: policy retrieval backends and the search_policies tool."""

from __future__ import annotations

import json
from dataclasses import replace

import psycopg
import pytest
from psycopg.rows import dict_row

from quilora.search.chunking import load_policies
from quilora.search.embed import embed_policies
from quilora.search.embeddings import HashingEmbedder
from quilora.search.policies import search, search_fts, search_hybrid, search_vector
from quilora.seed import DATA_DIR
from quilora.tools import build_registry
from quilora.tools.base import SessionState, ToolContext
from tests.conftest import _db_url


def test_fts_finds_keyword_queries(database):
    with database.connection() as conn:
        hits = search_fts(conn, "return window days", 3)
    assert hits[0].chunk_id == "RET-1"
    assert hits[0].citation == "Returns Policy §1 (Return window)"


def test_fts_handles_punctuation_and_empty_queries(database):
    with database.connection() as conn:
        assert search_fts(conn, "¿?¡!", 3) == []
        assert search_fts(conn, "o'reilly's & | ! (discount)", 3)[0].chunk_id == "PAY-3"


@pytest.fixture()
def embedded_db(database):
    """Embed the chunks with the test hashing embedder, then restore NULL embeddings."""
    embedder = HashingEmbedder()
    with psycopg.connect(_db_url()) as conn:
        embed_policies(conn, embedder)
    yield embedder
    with psycopg.connect(_db_url()) as conn:
        conn.execute("UPDATE policy_chunks SET embedding = NULL, embedding_model = NULL")


def test_vector_and_hybrid_queries_run(embedded_db):
    with psycopg.connect(_db_url(), row_factory=dict_row) as conn:
        vec = search_vector(conn, "return window days", 3, embedded_db)
        hyb = search_hybrid(conn, "return window days", 3, embedded_db)
    assert len(vec) == 3 and all(-1 <= h.score <= 1 for h in vec)
    assert hyb[0].chunk_id == "RET-1"  # both signals agree on the keyword query


def test_search_falls_back_to_fts_without_embeddings(database):
    with database.connection() as conn:
        hits, used = search(conn, "discount code", backend="hybrid", embedder=HashingEmbedder())
    assert used == "fts" and hits[0].chunk_id == "PAY-3"


def test_search_policies_tool_returns_citations(database, settings):
    ctx = ToolContext(db=database, settings=settings, state=SessionState(), session_id="t",
                      turn_index=1)
    outcome = build_registry().execute("search_policies", {"query": "return window"}, ctx)
    data = json.loads(outcome.content())
    assert data["results"][0]["policy_id"] == "RET-1"
    assert "Returns Policy §1" in data["hint"]


def test_tool_with_no_results_tells_model_not_to_guess(database, settings):
    ctx = ToolContext(db=database, settings=replace(settings, policy_search_backend="fts"),
                      state=SessionState(), session_id="t", turn_index=1)
    data = json.loads(build_registry().execute(
        "search_policies", {"query": "zzzz qqqq"}, ctx).content())
    assert data["results"] == [] and "Do not guess" in data["hint"]


def test_labelled_queries_reference_existing_chunks():
    import yaml

    ids = {c.id for c in load_policies(DATA_DIR / "policies")}
    queries = yaml.safe_load((DATA_DIR.parent / "evals/retrieval/queries.yaml").read_text())
    for q in queries:
        assert set(q["relevant"]) <= ids, q
