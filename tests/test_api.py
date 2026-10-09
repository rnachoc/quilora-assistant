"""Phase 9: HTTP API and durable sessions.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from quilora.agent.loop import Agent
from quilora.agent.session import ConcurrentUpdateError, Conversation, PostgresSessionStore
from quilora.api.app import create_app
from quilora.tools import build_registry
from tests.fakes import ScriptedModel, text, tool_call


@pytest.fixture()
def client_with(database, settings):
    def make(steps):
        agent = Agent(model=ScriptedModel(steps), registry=build_registry(), settings=settings,
                      db=database)
        app = create_app(settings, agent=agent, store=PostgresSessionStore(database))
        return TestClient(app)
    return make


def test_conversation_persists_across_requests(client_with):
    steps = [
        tool_call("check_stock", {"product_id": "QL-TRS-001", "color": "black", "size": "M"}),
        text("Sí, queda la M en negro."),
        text("De nada."),
    ]
    with client_with(steps) as client:
        first = client.post("/api/chat", json={"message": "¿Queda la M en negro del Iris?"})
        assert first.status_code == 200
        body = first.json()
        assert body["reply"] == "Sí, queda la M en negro."
        assert body["meta"]["tools"][0] == {"name": "check_stock", "ok": True,
                                            "error_code": None,
                                            "duration_ms": body["meta"]["tools"][0]["duration_ms"]}
        sid = body["session_id"]

        second = client.post("/api/chat", json={"session_id": sid, "message": "gracias"})
        assert second.json()["session_id"] == sid

        transcript = client.get(f"/api/sessions/{sid}").json()
        assert [m["role"] for m in transcript] == ["user", "assistant", "user", "assistant"]
        assert "check_stock" not in str(transcript)  # no tool internals for the customer


def test_handoff_is_reported_to_the_widget(client_with):
    steps = [
        tool_call("handoff_to_human", {"reason": "customer_requested_human",
                                       "summary": "Customer asks for a person, no order given."}),
        text("Te paso con el equipo."),
    ]
    with client_with(steps) as client:
        body = client.post("/api/chat", json={"message": "quiero hablar con una persona"}).json()
    assert body["handed_off"] is True and body["ticket_id"].startswith("HT-")


def test_unknown_session_and_validation(client_with):
    with client_with([]) as client:
        assert client.post("/api/chat", json={"session_id": "nope", "message": "hola"}
                           ).status_code == 404
        assert client.post("/api/chat", json={"message": ""}).status_code == 422
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").json() == {"status": "ready"}


def test_optimistic_locking(database):
    store = PostgresSessionStore(database)
    conv = Conversation()
    store.save(conv)
    a, b = store.load(conv.id), store.load(conv.id)
    a.turn_count = 1
    store.save(a)
    b.turn_count = 2
    with pytest.raises(ConcurrentUpdateError):
        store.save(b)
    assert store.load(conv.id).turn_count == 1


def test_session_state_round_trips(database):
    store = PostgresSessionStore(database)
    conv = Conversation()
    conv.state.verified_orders["1043"] = "lucia.romero@example.com"
    conv.messages.append({"role": "user", "content": "hola"})
    store.save(conv)
    loaded = store.load(conv.id)
    assert loaded.state.verified_orders == {"1043": "lucia.romero@example.com"}
    assert loaded.messages == conv.messages
