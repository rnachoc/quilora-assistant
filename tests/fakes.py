"""Test doubles: a scripted model that replays prepared responses."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import Any

from quilora.agent.model import ModelError, ModelResponse, TokenUsage

_ids = itertools.count(1)


def text(reply: str) -> ModelResponse:
    return ModelResponse(content=[{"type": "text", "text": reply}], stop_reason="end_turn",
                         model="fake-model", usage=TokenUsage(100, 20))


def tool_call(name: str, args: dict[str, Any], *more: tuple[str, dict[str, Any]],
              preamble: str | None = None) -> ModelResponse:
    content: list[dict[str, Any]] = []
    if preamble:
        content.append({"type": "text", "text": preamble})
    for n, a in ((name, args), *more):
        content.append({"type": "tool_use", "id": f"toolu_{next(_ids)}", "name": n, "input": a})
    return ModelResponse(content=content, stop_reason="tool_use", model="fake-model",
                         usage=TokenUsage(150, 30))


Step = ModelResponse | Exception | Callable[[list[dict[str, Any]]], ModelResponse]


class ScriptedModel:
    """Returns the next scripted step on every call and records what it was sent."""

    model = "fake-model"

    def __init__(self, steps: list[Step]) -> None:
        self.steps = list(steps)
        self.calls: list[dict[str, Any]] = []

    def create(self, *, system, messages, tools, max_tokens) -> ModelResponse:
        self.calls.append({"system": system, "messages": [dict(m) for m in messages],
                           "tools": tools})
        if not self.steps:
            raise AssertionError("ScriptedModel ran out of steps")
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        if callable(step):
            return step(messages)
        return step


def model_down() -> ModelError:
    return ModelError("connection refused", retryable=True)
