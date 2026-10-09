"""OpenTelemetry tracing setup.

Every customer turn produces one trace:

    chat.turn                          session, turn index, stop reason, tokens, cost, flags
    ├── chat claude-sonnet-5-5         one span per model call (GenAI semantic conventions)
    ├── execute_tool check_stock       one span per tool call (redacted arguments, error code)
    └── chat claude-sonnet-5-5

Attribute names follow the OpenTelemetry GenAI semantic conventions
(https://opentelemetry.io/docs/specs/semconv/gen-ai/), which are still marked as
"Development" and may change; check that page when upgrading. Prompt and reply TEXT is not
recorded (personal data); only sizes, names, codes and redacted tool arguments.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import re
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from quilora.config import Settings

_EMAIL = re.compile(r"([^@\s])[^@\s]*(@[^@\s]+)")


def setup_tracing(settings: Settings) -> TracerProvider | None:
    """Install a global tracer provider if an exporter is configured; otherwise no-op."""
    if not settings.otel_endpoint and not settings.otel_console:
        return None
    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)
    if settings.otel_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        endpoint = settings.otel_endpoint.rstrip("/") + "/v1/traces"
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    if settings.otel_console:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    return provider


def redact(value: Any) -> Any:
    """Mask emails in tool arguments before they are attached to spans."""
    if isinstance(value, str):
        return _EMAIL.sub(r"\1***\2", value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value
