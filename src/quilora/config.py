"""Application settings, read once from environment variables.

A frozen dataclass keeps configuration explicit and immutable; see `.env.example` for
documentation of every variable.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date

from quilora.env import load_dotenv


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name) or default)


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name) or default)


@dataclass(frozen=True)
class Settings:
    """All runtime configuration in one immutable object (see .env.example)."""
    database_url: str = "postgresql://quilora:quilora_dev@localhost:5432/quilora"
    anthropic_api_key: str | None = None
    agent_model: str = "claude-sonnet-5-5"
    judge_model: str = "claude-haiku-5-5"
    agent_max_tokens: int = 1024
    agent_max_iterations: int = 6
    model_timeout_s: float = 30.0
    tool_timeout_s: float = 5.0
    store_today: date | None = None
    policy_search_backend: str = "fts"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    otel_endpoint: str | None = None
    otel_service_name: str = "quilora-assistant"
    otel_console: bool = False
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:4200"])

    def today(self) -> date:
        """The store's notion of "today". Fixed in dev/evals so results are reproducible."""
        return self.store_today or date.today()


def load_settings(dotenv_path: str = ".env") -> Settings:
    """Read settings from the environment (and .env), validating the few that have fixed values."""
    load_dotenv(dotenv_path)
    today = os.environ.get("STORE_TODAY") or None
    backend = (os.environ.get("POLICY_SEARCH_BACKEND") or "fts").lower()
    if backend not in {"fts", "vector", "hybrid"}:
        raise ValueError(f"POLICY_SEARCH_BACKEND must be fts, vector or hybrid, got {backend!r}")
    return Settings(
        database_url=os.environ.get("DATABASE_URL") or Settings.database_url,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        agent_model=os.environ.get("AGENT_MODEL") or Settings.agent_model,
        judge_model=os.environ.get("JUDGE_MODEL") or Settings.judge_model,
        agent_max_tokens=_int("AGENT_MAX_TOKENS", Settings.agent_max_tokens),
        agent_max_iterations=_int("AGENT_MAX_ITERATIONS", Settings.agent_max_iterations),
        model_timeout_s=_float("MODEL_TIMEOUT_SECONDS", Settings.model_timeout_s),
        tool_timeout_s=_float("TOOL_TIMEOUT_SECONDS", Settings.tool_timeout_s),
        store_today=date.fromisoformat(today) if today else None,
        policy_search_backend=backend,
        embedding_model=os.environ.get("EMBEDDING_MODEL") or Settings.embedding_model,
        otel_endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or None,
        otel_service_name=os.environ.get("OTEL_SERVICE_NAME") or Settings.otel_service_name,
        otel_console=os.environ.get("OTEL_CONSOLE") == "1",
        cors_origins=[
            o.strip()
            for o in (os.environ.get("CORS_ORIGINS") or "http://localhost:4200").split(",")
            if o.strip()
        ],
    )
