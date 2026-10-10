"""Application settings, read once from environment variables.

A frozen dataclass keeps configuration explicit and immutable; see `.env.example` for
documentation of every variable.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from quilora.env import load_dotenv
from quilora.paths import DATA_DIR
from quilora.store.profile import StoreProfile, load_profile


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name) or default)


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name) or default)


@dataclass(frozen=True)
class Settings:
    """All runtime configuration in one immutable object (see .env.example)."""
    database_url: str = "postgresql://quilora:quilora_dev@localhost:5432/quilora"
    anthropic_api_key: str | None = None
    # live = Claude via the Anthropic API; scripted = deterministic demo model, no API key or
    # cost (ADR 0023).
    agent_mode: str = "live"
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
    # Directory with store.yaml, policies/ and generated/ (the shop being served).
    store_dir: str = str(DATA_DIR)
    # Public demo guard (ADR 0022). Empty credentials = no login (local development).
    demo_username: str | None = None
    demo_password: str | None = field(default=None, repr=False)
    # Customer messages accepted per calendar day across all visitors; 0 = no cap.
    daily_message_limit: int = 0
    # Built Angular widget to serve from the API itself (single-service deploy); empty = off.
    web_dist_dir: str | None = None
    # Public landing page (a directory with index.html). When set it is served at "/" without
    # login and the widget moves to /demo/ (ADR 0022).
    landing_dir: str | None = None

    @property
    def store(self) -> StoreProfile:
        """The validated profile of the shop this assistant serves (cached)."""
        return load_profile(self.store_dir)

    def today(self) -> date:
        """The store's notion of "today". Fixed in dev/evals so results are reproducible."""
        return self.store_today or datetime.now(ZoneInfo(self.store.timezone)).date()

    def now(self) -> datetime:
        """Current store-local time. With STORE_TODAY set it is that day at 10:00, so delivery
        estimates (which depend on the order cut-off hour) are reproducible too."""
        tz = ZoneInfo(self.store.timezone)
        if self.store_today:
            return datetime.combine(self.store_today, time(10, 0), tzinfo=tz)
        return datetime.now(tz)


def load_settings(dotenv_path: str = ".env") -> Settings:
    """Read settings from the environment (and .env), validating the few that have fixed values."""
    load_dotenv(dotenv_path)
    today = os.environ.get("STORE_TODAY") or None
    backend = (os.environ.get("POLICY_SEARCH_BACKEND") or "fts").lower()
    if backend not in {"fts", "vector", "hybrid"}:
        raise ValueError(f"POLICY_SEARCH_BACKEND must be fts, vector or hybrid, got {backend!r}")
    mode = (os.environ.get("AGENT_MODE") or "live").lower()
    if mode not in {"live", "scripted"}:
        raise ValueError(f"AGENT_MODE must be live or scripted, got {mode!r}")
    demo_username = os.environ.get("DEMO_USERNAME") or None
    demo_password = os.environ.get("DEMO_PASSWORD") or None
    if bool(demo_username) != bool(demo_password):
        raise ValueError("Set both DEMO_USERNAME and DEMO_PASSWORD, or neither.")
    # Fail closed: a deployment that declares it needs a login refuses to start without one,
    # so a forgotten variable cannot leave the demo (and the API key's budget) open.
    if os.environ.get("REQUIRE_DEMO_AUTH") == "1" and not demo_password:
        raise ValueError("REQUIRE_DEMO_AUTH=1 but DEMO_USERNAME/DEMO_PASSWORD are not set.")
    daily_limit = _int("DAILY_MESSAGE_LIMIT", 0)
    if daily_limit < 0:
        raise ValueError("DAILY_MESSAGE_LIMIT must be 0 (no cap) or positive.")
    return Settings(
        database_url=os.environ.get("DATABASE_URL") or Settings.database_url,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        agent_mode=mode,
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
        store_dir=os.environ.get("STORE_DIR") or str(DATA_DIR),
        demo_username=demo_username,
        demo_password=demo_password,
        daily_message_limit=daily_limit,
        web_dist_dir=os.environ.get("WEB_DIST_DIR") or None,
        landing_dir=os.environ.get("LANDING_DIR") or None,
        cors_origins=[
            o.strip()
            for o in (os.environ.get("CORS_ORIGINS") or "http://localhost:4200").split(",")
            if o.strip()
        ],
    )
