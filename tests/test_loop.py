"""Phase 3: the agent loop, driven by a scripted model (no network).

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from quilora.agent.loop import Agent
from quilora.agent.model import ModelResponse
from quilora.agent.session import Conversation
from quilora.tools import build_registry
from tests.fakes import ScriptedModel, model_down, text, tool_call


@pytest.fixture()
def make_agent(database, settings):
    def factory(steps, **overrides):
        model = ScriptedModel(steps)
        agent = Agent(model=model, registry=build_registry(),
                      settings=replace(settings, **overrides), db=database)
        return agent, model
    return factory


def assert_history_is_valid(messages):
    """Roles alternate and every tool_use is answered by a tool_result with the same id."""
    roles = [m["role"] for m in messages]
    assert roles[0] == "user"
    assert all(a != b for a, b in zip(roles, roles[1:], strict=False)), roles
    for i, m in enumerate(messages):
        if m["role"] == "assistant" and isinstance(m["content"], list):
            ids = {b["id"] for b in m["content"] if b["type"] == "tool_use"}
            if ids:
                answered = {b["tool_use_id"] for b in messages[i + 1]["content"]}
                assert ids == answered


def test_direct_answer_without_tools(make_agent):
    agent, model = make_agent([text("¡Hola! ¿En qué te ayudo?")])
    conv = Conversation()
    result = agent.run_turn(conv, "hola")
    assert result.reply == "¡Hola! ¿En qué te ayudo?"
    assert result.iterations == 1 and result.tool_calls == []
    assert model.calls[0]["tools"]  # tool definitions are always offered
    assert "Quilora" in model.calls[0]["system"]


def test_tool_call_round_trip(make_agent):
    def answer(messages):
        payload = json.loads(messages[-1]["content"][0]["content"])
        assert messages[-1]["content"][0]["is_error"] is False
        return text(f"Sí, en negro: {payload['variants'][0]['availability']}")

    agent, model = make_agent([
        tool_call("check_stock", {"product_id": "QL-TRS-001", "color": "black", "size": "M"}),
        answer,
    ])
    conv = Conversation()
    result = agent.run_turn(conv, "¿Queda la M en negro del QL-TRS-001?")
    assert result.reply == "Sí, en negro: in_stock"
    assert [c.name for c in result.tool_calls] == ["check_stock"]
    assert result.iterations == 2
    assert result.usage.input_tokens == 250
    assert_history_is_valid(conv.messages)


def test_parallel_tool_calls_are_all_answered(make_agent):
    agent, _ = make_agent([
        tool_call("get_product", {"product_id": "QL-TRS-001"},
                  ("get_product", {"product_id": "QL-DRS-001"})),
        text("Aquí tienes los dos."),
    ])
    conv = Conversation()
    agent.run_turn(conv, "compara QL-TRS-001 y QL-DRS-001")
    assert len(conv.messages[2]["content"]) == 2
    assert_history_is_valid(conv.messages)


def test_tool_errors_are_returned_to_the_model_flagged(make_agent):
    def recover(messages):
        block = messages[-1]["content"][0]
        assert block["is_error"] is True
        assert json.loads(block["content"])["error"]["code"] == "INVALID_INPUT"
        return text("¿Me dices el número de pedido y el email?")

    agent, _ = make_agent([tool_call("get_order_status", {"order_id": 1043}), recover])
    result = agent.run_turn(Conversation(), "¿dónde está mi pedido 1043?")
    assert result.tool_calls[0].error_code == "INVALID_INPUT"


def test_iteration_budget_gives_a_safe_fallback(make_agent):
    loop_forever = [tool_call("get_product", {"product_id": "QL-TRS-001"}) for _ in range(3)]
    agent, model = make_agent(loop_forever, agent_max_iterations=3)
    conv = Conversation()
    result = agent.run_turn(conv, "dime todo sobre el pantalón")
    assert result.stop_reason == "max_iterations"
    assert "equipo" in result.reply  # Spanish fallback offering the support team
    assert len(model.calls) == 3
    assert_history_is_valid(conv.messages)


def test_model_failure_gives_fallback_and_keeps_history_usable(make_agent):
    agent, _ = make_agent([model_down(), text("Ya funciono.")])
    conv = Conversation()
    first = agent.run_turn(conv, "hola, quiero ayuda con mi pedido")
    assert first.stop_reason == "model_error"
    second = agent.run_turn(conv, "¿sigues ahí?")
    assert second.reply == "Ya funciono."
    assert_history_is_valid(conv.messages)


def test_truncated_tool_call_is_never_executed(make_agent):
    truncated = ModelResponse(
        content=[{"type": "tool_use", "id": "toolu_x", "name": "get_order_status",
                  "input": {"order_id": 1043}}],
        stop_reason="max_tokens", model="fake-model")
    agent, _ = make_agent([truncated])
    conv = Conversation()
    result = agent.run_turn(conv, "where is my order")
    assert result.stop_reason == "max_tokens" and result.tool_calls == []
    assert_history_is_valid(conv.messages)


def test_oversized_input_is_rejected_without_calling_the_model(make_agent):
    agent, model = make_agent([])
    result = agent.run_turn(Conversation(), "a" * 5000)
    assert result.stop_reason == "rejected_input" and model.calls == []
