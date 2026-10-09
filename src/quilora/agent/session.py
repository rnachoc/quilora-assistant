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
