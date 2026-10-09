"""Conversations and where they are stored."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from quilora.tools.base import SessionState


@dataclass
class Conversation:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    messages: list[dict[str, Any]] = field(default_factory=list)
    state: SessionState = field(default_factory=SessionState)
    turn_count: int = 0
    version: int = 0  # optimistic locking for the Postgres store


class ConcurrentUpdateError(Exception):
    """Two requests tried to update the same conversation at the same time."""


class SessionStore(Protocol):
    def load(self, session_id: str) -> Conversation | None: ...
    def save(self, conv: Conversation) -> None: ...


class InMemorySessionStore:
    """For the CLI, tests and evaluations. Not shared across processes."""

    def __init__(self) -> None:
        self._data: dict[str, Conversation] = {}

    def load(self, session_id: str) -> Conversation | None:
        conv = self._data.get(session_id)
        return copy.deepcopy(conv) if conv else None

    def save(self, conv: Conversation) -> None:
        current = self._data.get(conv.id)
        if current and current.version != conv.version:
            raise ConcurrentUpdateError(conv.id)
        conv.version += 1
        self._data[conv.id] = copy.deepcopy(conv)


class PostgresSessionStore:
    """Durable sessions shared by every API replica, with optimistic locking.

    Why optimistic and not `SELECT ... FOR UPDATE`? A turn takes seconds (model calls);
    holding a row lock and a transaction open that long would tie up connections. Instead
    each save checks the version it loaded; a concurrent save makes it fail (HTTP 409).
    """

    def __init__(self, db) -> None:
        self.db = db

    def load(self, session_id: str) -> Conversation | None:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT id, messages, state, turn_count, version FROM chat_sessions"
                " WHERE id = %s", (session_id,)).fetchone()
        if row is None:
            return None
        return Conversation(id=row["id"], messages=row["messages"],
                            state=SessionState.from_dict(row["state"]),
                            turn_count=row["turn_count"], version=row["version"])

    def save(self, conv: Conversation) -> None:
        from psycopg.errors import UniqueViolation
        from psycopg.types.json import Jsonb

        with self.db.connection() as conn:
            if conv.version == 0:
                try:
                    conn.execute(
                        "INSERT INTO chat_sessions (id, messages, state, turn_count, version)"
                        " VALUES (%s, %s, %s, %s, 1)",
                        (conv.id, Jsonb(conv.messages), Jsonb(conv.state.to_dict()),
                         conv.turn_count))
                except UniqueViolation as exc:
                    raise ConcurrentUpdateError(conv.id) from exc
                conv.version = 1
                return
            updated = conn.execute(
                "UPDATE chat_sessions SET messages = %s, state = %s, turn_count = %s,"
                " version = version + 1, updated_at = now()"
                " WHERE id = %s AND version = %s",
                (Jsonb(conv.messages), Jsonb(conv.state.to_dict()), conv.turn_count, conv.id,
                 conv.version))
            if updated.rowcount != 1:
                raise ConcurrentUpdateError(conv.id)
            conv.version += 1

    def purge_older_than(self, days: int) -> int:
        """Delete inactive conversations (data minimisation). Run it from a scheduled job."""
        with self.db.connection() as conn:
            cur = conn.execute(
                "DELETE FROM chat_sessions WHERE updated_at < now() - make_interval(days => %s)",
                (days,))
            return cur.rowcount
