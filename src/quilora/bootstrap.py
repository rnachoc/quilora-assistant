"""Wire the application together from settings (used by the CLI, the API and the evals)."""

from __future__ import annotations

from quilora.agent.loop import Agent
from quilora.agent.model import AnthropicModelClient, ModelClient
from quilora.config import Settings
from quilora.db import Database
from quilora.tools import build_registry


def build_agent(settings: Settings, db: Database | None = None,
                model: ModelClient | None = None, prompt_name: str = "system") -> Agent:
    db = db or Database(settings.database_url)
    model = model or AnthropicModelClient(settings.anthropic_api_key, settings.agent_model,
                                          settings.model_timeout_s)
    return Agent(model=model, registry=build_registry(), settings=settings, db=db,
                 prompt_name=prompt_name)
