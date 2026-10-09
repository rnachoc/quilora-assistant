"""Tool plumbing: specs, the registry, validation, timeouts and model-friendly errors.

Flow for every tool call the model proposes:

    model proposes {name, input}
      -> registry looks up the spec            (unknown tool  -> UNKNOWN_TOOL)
      -> Pydantic validates the input          (bad input     -> INVALID_INPUT + field details)
      -> handler runs with a timeout           (slow          -> TIMEOUT, retryable)
      -> handler may refuse with a ToolError   (business rule -> its own code + hint)
      -> result is serialised to JSON for the model

The model only ever sees JSON payloads. Errors follow one shape so the system prompt can
teach a single recovery strategy: {"error": {"code", "message", "hint", "retryable"}}.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ValidationError

from quilora.config import Settings
from quilora.db import Database

log = logging.getLogger(__name__)

# Shared worker pool for tool execution, so a slow tool can be abandoned after the timeout.
_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="tool")


class ToolError(Exception):
    """A refusal or failure the model should understand and act on."""

    def __init__(self, code: str, message: str, hint: str | None = None,
                 retryable: bool = False, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.retryable = retryable
        self.details = details or {}

    def payload(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message,
                                 "retryable": self.retryable}
        if self.hint:
            error["hint"] = self.hint
        if self.details:
            error["details"] = self.details
        return {"error": error}


@dataclass
class SessionState:
    """Per-conversation facts that the *code* relies on to authorise tool calls.

    This is deliberately not left to the model: e.g. `verified_orders` is what allows a
    return request, regardless of what the conversation text claims.
    """

    verified_orders: dict[str, str] = field(default_factory=dict)  # order_id -> email (lower)
    failed_verifications: int = 0
    pending_returns: dict[str, dict[str, Any]] = field(default_factory=dict)  # token -> proposal
    handoff_ticket_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified_orders": self.verified_orders,
            "failed_verifications": self.failed_verifications,
            "pending_returns": self.pending_returns,
            "handoff_ticket_id": self.handoff_ticket_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SessionState:
        data = data or {}
        return cls(
            verified_orders=dict(data.get("verified_orders", {})),
            failed_verifications=int(data.get("failed_verifications", 0)),
            pending_returns=dict(data.get("pending_returns", {})),
            handoff_ticket_id=data.get("handoff_ticket_id"),
        )


@dataclass
class ToolContext:
    db: Database
    settings: Settings
    state: SessionState
    session_id: str
    turn_index: int
    embedder: Any = None  # set when vector policy search is enabled (phase 4)


Handler = Callable[[ToolContext, Any], dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Handler
    mutates: bool = False  # True only for tools that change business data

    def definition(self) -> dict[str, Any]:
        """Tool definition in the Messages API format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": clean_schema(inline_refs(self.input_model.model_json_schema())),
        }


@dataclass
class ToolOutcome:
    name: str
    input: dict[str, Any]
    payload: dict[str, Any]
    is_error: bool
    duration_ms: float

    @property
    def error_code(self) -> str | None:
        return self.payload["error"]["code"] if self.is_error else None

    def content(self) -> str:
        return to_json(self.payload)


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Replace local `$ref`s with their definitions, producing one flat, self-contained schema.

    Nested models (e.g. a list of return items) make Pydantic emit `$defs` + `$ref`. Inlining
    keeps the schema simple for the model to read and avoids relying on `$ref` support.
    """
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                merged = {**defs[ref.split("/")[-1]], **{k: v for k, v in node.items()
                                                          if k != "$ref"}}
                return resolve(merged)
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(x) for x in node]
        return node

    return resolve(schema)


def clean_schema(schema: Any) -> Any:
    """Drop Pydantic's auto-generated `title` keys: they cost tokens and add nothing."""
    if isinstance(schema, dict):
        cleaned = {}
        for key, value in schema.items():
            if key == "title" and isinstance(value, str):
                continue
            if key == "properties" and isinstance(value, dict):
                cleaned[key] = {name: clean_schema(sub) for name, sub in value.items()}
            else:
                cleaned[key] = clean_schema(value)
        return cleaned
    if isinstance(schema, list):
        return [clean_schema(x) for x in schema]
    return schema


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    raise TypeError(f"Not JSON serialisable: {type(value)}")


def to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=_json_default, ensure_ascii=False)


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec]) -> None:
        names = [s.name for s in specs]
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate tool names: {names}")
        self._specs = {s.name: s for s in specs}

    @property
    def specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def definitions(self) -> list[dict[str, Any]]:
        return [s.definition() for s in self._specs.values()]

    def execute(self, name: str, raw_input: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
        started = time.perf_counter()

        def done(payload: dict[str, Any], is_error: bool) -> ToolOutcome:
            return ToolOutcome(name, raw_input, payload, is_error,
                               (time.perf_counter() - started) * 1000)

        spec = self._specs.get(name)
        if spec is None:
            err = ToolError("UNKNOWN_TOOL", f"There is no tool named {name!r}.",
                            hint=f"Available tools: {', '.join(self._specs)}.")
            return done(err.payload(), True)

        try:
            args = spec.input_model.model_validate(raw_input)
        except ValidationError as exc:
            problems = [
                {"field": ".".join(str(p) for p in e["loc"]) or "(input)", "problem": e["msg"]}
                for e in exc.errors(include_url=False)
            ]
            err = ToolError("INVALID_INPUT", "The tool input is not valid.",
                            hint="Fix the listed fields, or ask the customer for the missing "
                                 "information, then call the tool again.",
                            details={"problems": problems})
            return done(err.payload(), True)

        future = _EXECUTOR.submit(spec.handler, ctx, args)
        try:
            return done(future.result(timeout=ctx.settings.tool_timeout_s), False)
        except FutureTimeout:
            future.cancel()
            err = ToolError("TIMEOUT", "The store system took too long to answer.",
                            hint="Retry once. If it fails again, apologise and offer a handoff.",
                            retryable=True)
            return done(err.payload(), True)
        except ToolError as exc:
            return done(exc.payload(), True)
        except Exception:  # never leak stack traces or internals to the model
            log.exception("Tool %s failed", name)
            err = ToolError("INTERNAL_ERROR", "The store system had an unexpected problem.",
                            hint="Do not retry. Apologise and offer to transfer the customer "
                                 "to the support team.")
            return done(err.payload(), True)
