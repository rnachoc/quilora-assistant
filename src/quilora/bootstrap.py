"""Wire the application together from settings (used by the CLI, the API and the evals).

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

from quilora.agent.loop import Agent
from quilora.agent.model import AnthropicModelClient, ModelClient
from quilora.config import Settings
from quilora.db import Database
from quilora.tools import build_registry


def build_agent(settings: Settings, db: Database | None = None,
                model: ModelClient | None = None, prompt_name: str = "system") -> Agent:
    """Create a fully wired Agent (database, model client, tools, embedder) from settings."""
    db = db or Database(settings.database_url)
    model = model or build_model(settings)
    return Agent(model=model, registry=build_registry(), settings=settings, db=db,
                 prompt_name=prompt_name, embedder=build_embedder(settings))


def build_model(settings: Settings) -> ModelClient:
    """Claude for real use; the scripted demo model when AGENT_MODE=scripted (no key, no cost)."""
    if settings.agent_mode == "scripted":
        from quilora.agent.scripted import ScriptedDemoModel

        return ScriptedDemoModel()
    return AnthropicModelClient(settings.anthropic_api_key, settings.agent_model,
                                settings.model_timeout_s)


def build_embedder(settings: Settings):
    """Only load the embedding model when a vector-based backend is configured."""
    if settings.policy_search_backend == "fts":
        return None
    from quilora.search.embeddings import FastEmbedEmbedder

    return FastEmbedEmbedder(settings.embedding_model)
