"""Shared fixtures.

Tests marked `db` run against a real PostgreSQL (with pgvector) pointed to by
TEST_DATABASE_URL or DATABASE_URL. They are skipped when no database is reachable, so
`pytest` always works on a laptop; CI provides a Postgres service container.
"""

from __future__ import annotations

import os
from datetime import date

import psycopg
import pytest

from quilora.config import Settings
from quilora.db import Database, migrate
from quilora.seed import load_all, reset_writes

DEFAULT_URL = "postgresql://quilora:quilora_dev@localhost:5432/quilora"


def _db_url() -> str:
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or DEFAULT_URL


@pytest.fixture(scope="session")
def database() -> Database:
    url = _db_url()
    try:
        with psycopg.connect(url, connect_timeout=2) as conn:
            migrate(conn)
            load_all(conn)
    except psycopg.OperationalError as exc:  # pragma: no cover - depends on environment
        pytest.skip(f"PostgreSQL not available at {url}: {exc}")
    db = Database(url, min_size=1, max_size=4)
    yield db
    db.close()


@pytest.fixture(autouse=True)
def _isolated_writes(request):
    """Tests that touch the database start without returns, tickets or audit entries."""
    if "database" in request.fixturenames:
        db = request.getfixturevalue("database")
        with db.connection() as conn:
            reset_writes(conn)
    yield


@pytest.fixture()
def settings() -> Settings:
    return Settings(database_url=_db_url(), store_today=date(2026, 10, 1))


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "database" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.db)
