"""Phase 10: traces for each turn, model call and tool call, without personal data."""

from __future__ import annotations

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from quilora.agent.loop import Agent
from quilora.agent.session import Conversation
from quilora.observability import redact
from quilora.tools import build_registry
from tests.fakes import ScriptedModel, text, tool_call


def test_turn_produces_a_trace_with_genai_attributes(database, settings):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    model = ScriptedModel([
        tool_call("get_order_status", {"order_id": 1043, "email": "lucia.romero@example.com"}),
        text("Tu pedido está entregado."),
    ])
    agent = Agent(model=model, registry=build_registry(), settings=settings, db=database,
                  tracer=provider.get_tracer("test"))
    agent.run_turn(Conversation(id="s-1"), "pedido 1043 lucia.romero@example.com")

    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert set(spans) == {"chat.turn", "chat fake-model", "execute_tool get_order_status"}
    turn = spans["chat.turn"].attributes
    assert turn["quilora.turn.iterations"] == 2 and turn["gen_ai.usage.input_tokens"] == 250
    tool = spans["execute_tool get_order_status"].attributes
    assert tool["gen_ai.tool.name"] == "get_order_status"
    assert "lucia.romero" not in tool["quilora.tool.arguments"]  # redacted
    # Every span belongs to the same trace, with the turn as the parent.
    trace_ids = {s.context.trace_id for s in spans.values()}
    assert len(trace_ids) == 1
    assert spans["chat fake-model"].parent.span_id == spans["chat.turn"].context.span_id


def test_tool_errors_mark_the_span(database, settings):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    model = ScriptedModel([tool_call("get_product", {"product_id": "QL-XXX-999"}),
                           text("No lo encuentro.")])
    agent = Agent(model=model, registry=build_registry(), settings=settings, db=database,
                  tracer=provider.get_tracer("test"))
    agent.run_turn(Conversation(), "¿y el QL-XXX-999?")
    span = next(s for s in exporter.get_finished_spans() if s.name.startswith("execute_tool"))
    assert span.attributes["error.type"] == "PRODUCT_NOT_FOUND"
    assert not span.status.is_ok


def test_redact_masks_emails_in_nested_arguments():
    assert redact({"email": "lucia.romero@example.com", "items": ["a@b.com"]}) == {
        "email": "l***@example.com", "items": ["a***@b.com"]}
