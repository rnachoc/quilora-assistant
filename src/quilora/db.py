"""Database access: a connection pool and a tiny forward-only migration runner."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg_pool import ConnectionPool

from quilora.paths import MIGRATIONS_DIR

# Any single query slower than this is cancelled by Postgres itself. Tools also have an
# application-level timeout (TOOL_TIMEOUT_SECONDS); this is the second line of defence.
STATEMENT_TIMEOUT_MS = 3000


class Database:
    """Thin wrapper around a psycopg connection pool returning rows as dicts."""

    def __init__(self, url: str, min_size: int = 1, max_size: int = 10) -> None:
        self._pool = ConnectionPool(
            url,
            min_size=min_size,
            max_size=max_size,
            kwargs={
                "row_factory": dict_row,
                "options": f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
            },
            open=True,
        )

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        # The pool commits on clean exit and rolls back on exceptions.
        with self._pool.connection() as conn:
            yield conn

    def ping(self) -> bool:
        with self.connection() as conn:
            return conn.execute("SELECT 1 AS ok").fetchone()["ok"] == 1

    def close(self) -> None:
        self._pool.close()


def migrate(conn: psycopg.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending `*.sql` files in lexical order. Returns the names applied."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    with conn.cursor(row_factory=tuple_row) as cur:
        applied = {r[0] for r in cur.execute("SELECT name FROM schema_migrations").fetchall()}
    done = []
    for file in sorted(migrations_dir.glob("*.sql")):
        if file.name in applied:
            continue
        conn.execute(file.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (file.name,))
        done.append(file.name)
    return done
