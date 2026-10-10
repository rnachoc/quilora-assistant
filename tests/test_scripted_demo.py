"""Scripted demo model (ADR 0023): every sample question runs the real loop, tools and DB.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from quilora.agent.scripted import DEMO_SUGGESTIONS, ScriptedDemoModel, normalise
from quilora.agent.session import Conversation, PostgresSessionStore
from quilora.api.app import create_app
from quilora.bootstrap import build_agent

EMAIL = "lucia.romero@example.com"


@pytest.fixture()
def demo(database, settings):
    agent = build_agent(replace(settings, agent_mode="scripted"), db=database)

    def ask(text: str, conv: Conversation | None = None):
        conv = conv or Conversation(id=str(uuid.uuid4()))
        return agent.run_turn(conv, text), conv
    return ask


@pytest.mark.parametrize(("question", "tools", "expected"), [
    (DEMO_SUGGESTIONS[0], ["search_products"], "Garza Linen Midi Dress: 49,95 €"),
    (DEMO_SUGGESTIONS[1], ["search_products", "check_stock"], "queda la talla M en negro"),
    (DEMO_SUGGESTIONS[2], ["search_products", "get_size_recommendation"], "talla M"),
    (DEMO_SUGGESTIONS[3], ["search_policies"], "30 días naturales"),
    (DEMO_SUGGESTIONS[4], ["get_order_status"], "SwiftParcel"),
    (DEMO_SUGGESTIONS[5], ["get_order_status"], "ese número y ese email juntos"),
    (DEMO_SUGGESTIONS[6], ["get_order_status", "create_return_request"], "¿Confirmas"),
    (DEMO_SUGGESTIONS[7], [], "No puedo darte códigos de descuento"),
    (DEMO_SUGGESTIONS[8], ["handoff_to_human"], "HT-"),
])
def test_each_sample_question_uses_the_real_tools(demo, question, tools, expected):
    result, _ = demo(question)
    assert result.stop_reason == "end_turn"
    assert [c.name for c in result.tool_calls] == tools
    assert expected in result.reply
    assert result.cost_usd is None and result.model == "scripted-demo"


def test_suggestions_cover_every_scenario():
    assert len(DEMO_SUGGESTIONS) == 9


def test_return_needs_a_yes_in_a_new_message_and_then_is_created_once(demo):
    first, conv = demo(DEMO_SUGGESTIONS[6])
    assert "¿Confirmas" in first.reply and "RR-" not in first.reply

    done, conv = demo("Sí, confirmo", conv)
    assert [c.name for c in done.tool_calls] == ["create_return_request"]
    assert not done.tool_calls[0].is_error
    assert "RR-" in done.reply and "14 días" in done.reply

    # A second request for the same item is refused by the real eligibility rules.
    again, _ = demo(DEMO_SUGGESTIONS[6])
    assert "ya tiene una devolución solicitada" in again.reply


def test_saying_no_cancels_without_touching_the_database(demo):
    _first, conv = demo(DEMO_SUGGESTIONS[6])
    result, _ = demo("No, mejor no", conv)
    assert result.tool_calls == [] and "no tramito" in result.reply


def test_a_bare_yes_without_a_pending_return_falls_back(demo):
    result, _ = demo("sí")
    assert result.tool_calls == [] and "demo guionizada" in result.reply


def test_rewordings_still_match(demo):
    stock, _ = demo("¿Hay talla S en blanco del vestido Dalia?")
    assert [c.name for c in stock.tool_calls] == ["search_products", "check_stock"]
    size, _ = demo("Mido 175 cm y peso 70 kilos, ¿qué talla me pido en el vestido Garza?")
    assert size.tool_calls[-1].input["height_cm"] == 175


def test_off_script_questions_get_an_honest_explanation(demo):
    result, _ = demo("¿Qué tiempo hace hoy en Sevilla?")
    assert result.tool_calls == [] and "demo guionizada" in result.reply
    assert result.flags == []  # the fallback itself passes the real output guardrails


def test_order_status_without_email_asks_for_it_instead_of_calling_tools(demo):
    result, _ = demo("¿Dónde está mi pedido 1043?")
    assert result.tool_calls == [] and "email" in result.reply


def test_store_endpoint_announces_demo_mode(database, settings):
    scripted = replace(settings, agent_mode="scripted")
    agent = build_agent(scripted, db=database)
    with TestClient(create_app(scripted, agent=agent,
                               store=PostgresSessionStore(database))) as client:
        info = client.get("/api/store").json()
        reply = client.post("/api/chat", json={"message": DEMO_SUGGESTIONS[0]}).json()
    assert info["demo_mode"] is True and info["suggestions"] == DEMO_SUGGESTIONS
    assert reply["meta"]["cost_usd"] is None and reply["meta"]["model"] == "scripted-demo"


def test_live_mode_needs_no_script_and_shows_no_suggestions(database, settings):
    agent = build_agent(settings, db=database, model=ScriptedDemoModel())
    with TestClient(create_app(settings, agent=agent,
                               store=PostgresSessionStore(database))) as client:
        info = client.get("/api/store").json()
    assert info["demo_mode"] is False and info["suggestions"] == []


def test_normalise_strips_accents_and_case():
    assert normalise("Pantalón DEVOLUCIÓN ¿Sí?") == "pantalon devolucion ¿si?"
