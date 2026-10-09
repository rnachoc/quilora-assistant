"""Model client: the only module that talks to the Anthropic API.

The rest of the code depends on the small `ModelClient` protocol, so tests can drive the
agent loop with a scripted fake and we could swap providers without touching the loop.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_creation_input_tokens + other.cache_creation_input_tokens,
            self.cache_read_input_tokens + other.cache_read_input_tokens,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
        }


@dataclass
class ModelResponse:
    """Provider-neutral view of one model call.

    `content` holds plain dicts (`{"type": "text", ...}` / `{"type": "tool_use", ...}`), so
    a conversation can be stored as JSON and replayed to the API unchanged.
    """

    content: list[dict[str, Any]]
    stop_reason: str
    model: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    latency_ms: float = 0.0

    @property
    def text(self) -> str:
        return "\n".join(b["text"] for b in self.content if b["type"] == "text").strip()

    @property
    def tool_uses(self) -> list[dict[str, Any]]:
        return [b for b in self.content if b["type"] == "tool_use"]


class ModelError(Exception):
    """The model could not be reached or returned an error. `retryable` drives the fallback."""

    def __init__(self, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class ModelClient(Protocol):
    model: str

    def create(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> ModelResponse: ...


def _normalise_block(block: Any) -> dict[str, Any] | None:
    """Keep only the fields we send back to the API, so stored history stays portable."""
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    return None  # we do not enable thinking or server tools in this project


class AnthropicModelClient:
    """`ModelClient` backed by the official SDK (Messages API)."""

    def __init__(self, api_key: str | None, model: str, timeout_s: float = 30.0,
                 max_retries: int = 2) -> None:
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        # The SDK retries connection errors, 429 and 5xx with exponential backoff.
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s,
                                           max_retries=max_retries)
        self.model = model

    def create(self, *, system, messages, tools, max_tokens) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            # Top-level cache_control marks the last cacheable block of the request, so the
            # static prefix (tools + system) and the growing conversation are cached
            # incrementally across the iterations of one turn and across turns.
            "cache_control": {"type": "ephemeral"},
        }
        if tools:
            kwargs["tools"] = tools
        started = time.perf_counter()
        try:
            response = self._client.messages.create(**kwargs)
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
            raise ModelError(f"Model unreachable: {exc}", retryable=True) from exc
        except anthropic.RateLimitError as exc:
            raise ModelError("Model rate limited", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            raise ModelError(
                f"Model API error {exc.status_code}", retryable=exc.status_code >= 500
            ) from exc
        latency_ms = (time.perf_counter() - started) * 1000

        usage = response.usage
        return ModelResponse(
            content=[b for b in (_normalise_block(x) for x in response.content) if b],
            stop_reason=response.stop_reason or "end_turn",
            model=response.model,
            usage=TokenUsage(
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
                cache_read_input_tokens=usage.cache_read_input_tokens or 0,
            ),
            latency_ms=latency_ms,
        )
