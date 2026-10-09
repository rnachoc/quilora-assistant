"""Phase 5: returns with confirmation and handoff to a human."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from quilora.agent.loop import Agent
from quilora.agent.session import Conversation
from quilora.seed import reset_writes
from quilora.tools import build_registry
from quilora.tools.base import SessionState, ToolContext
from tests.fakes import ScriptedModel, text, tool_call

LUCIA = {"order_id": 1043, "email": "lucia.romero@example.com"}
TEE_RETURN = {"order_id": 1043, "items": [{"line_no": 1, "quantity": 1}], "reason": "doesnt_fit"}


@pytest.fixture()
def clean(database):
    with database.connection() as conn:
        reset_writes(conn)
    yield database


@pytest.fixture()
def session(clean, settings):
    """A tool context whose turn index can be advanced like a real conversation."""
    ctx = ToolContext(db=clean, settings=settings, state=SessionState(), session_id="s-1",
                      turn_index=1)
    registry = build_registry()

    def call(name, **args):
        outcome = registry.execute(name, args, ctx)
        return json.loads(outcome.content())

    return ctx, call


def _count(db, table):
    with db.connection() as conn:
        return conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]  # noqa: S608


def test_return_requires_verified_order(session):
    _, call = session
    assert call("create_return_request", **TEE_RETURN)["error"]["code"] == "ORDER_NOT_VERIFIED"


def test_full_two_phase_return(session, clean):
    ctx, call = session
    call("get_order_status", **LUCIA)

    proposal = call("create_return_request", **TEE_RETURN)
    assert proposal["status"] == "confirmation_required"
    assert proposal["summary"]["items"][0]["product_name"] == "Zafra Organic Cotton T-Shirt"
    assert _count(clean, "return_requests") == 0  # nothing written yet

    token = proposal["confirmation_token"]
    same_turn = call("create_return_request", **TEE_RETURN, confirmation_token=token)
    assert same_turn["error"]["code"] == "CONFIRMATION_NEEDS_CUSTOMER_REPLY"

    ctx.turn_index = 2  # the customer replied "yes"
    created = call("create_return_request", **TEE_RETURN, confirmation_token=token)
    assert created["status"] == "created" and created["return_id"].startswith("RR-")
    assert _count(clean, "return_requests") == 1
    assert _count(clean, "audit_log") == 1

    # Idempotent: replaying the confirmation does not create a second return.
    again = call("create_return_request", **TEE_RETURN, confirmation_token=token)
    assert again == {"status": "already_requested", "return_id": created["return_id"],
                     "note": "This exact return was already created; nothing new was done."}
    assert _count(clean, "return_requests") == 1

    # The order now shows the T-shirt as already returned.
    tee = call("get_order_status", **LUCIA)["items"][0]
    assert tee["return"]["reason"] == "already_returned"


def test_confirmation_must_match_the_summary(session):
    ctx, call = session
    call("get_order_status", **LUCIA)
    token = call("create_return_request", **TEE_RETURN)["confirmation_token"]
    ctx.turn_index = 2
    changed = {**TEE_RETURN, "items": [{"line_no": 2, "quantity": 1}]}
    assert call("create_return_request", **changed,
                confirmation_token=token)["error"]["code"] == "CONFIRMATION_MISMATCH"


def test_invented_token_is_rejected(session):
    ctx, call = session
    call("get_order_status", **LUCIA)
    ctx.turn_index = 3
    assert call("create_return_request", **TEE_RETURN,
                confirmation_token="made-up")["error"]["code"] == "CONFIRMATION_INVALID"


@pytest.mark.parametrize("order, email, reason", [
    (1041, "javier.campos@example.com", "final_sale"),
    (1031, "lucia.romero@example.com", "window_expired"),
    (1052, "liam.blanco@example.com", "not_delivered"),
])
def test_ineligible_items_are_refused_by_code(session, order, email, reason):
    _, call = session
    call("get_order_status", order_id=order, email=email)
    data = call("create_return_request", order_id=order, items=[{"line_no": 1}],
                reason="changed_mind")
    assert data["error"]["code"] == "ITEM_NOT_RETURNABLE"
    assert data["error"]["details"]["reason"] == reason


def test_quantity_and_line_validation(session):
    _, call = session
    call("get_order_status", **LUCIA)
    too_many = call("create_return_request", order_id=1043,
                    items=[{"line_no": 1, "quantity": 5}], reason="doesnt_fit")
    assert too_many["error"]["code"] == "QUANTITY_TOO_HIGH"
    bad_line = call("create_return_request", order_id=1043, items=[{"line_no": 9}],
                    reason="doesnt_fit")
    assert bad_line["error"]["code"] == "ITEM_NOT_IN_ORDER"


def test_defective_items_go_to_handoff(session):
    _, call = session
    call("get_order_status", **LUCIA)
    data = call("create_return_request", **{**TEE_RETURN, "reason": "defective_or_damaged"})
    assert data["error"]["code"] == "USE_HANDOFF"


def test_handoff_is_idempotent_per_session_and_prioritises_money(session, clean):
    _, call = session
    first = call("handoff_to_human", reason="customer_requested_human",
                 summary="Customer asks to speak to a person about order 1043 sizing.")
    assert first["status"] == "created" and first["priority"] == "normal"
    second = call("handoff_to_human", reason="refund_or_payment_dispute",
                  summary="Customer now also disputes a duplicate charge on order 1043.",
                  order_id=1043)
    assert second["ticket_id"] == first["ticket_id"] and second["status"] == "updated"
    assert second["priority"] == "high"
    assert _count(clean, "support_tickets") == 1


def test_handoff_summary_must_be_useful(session):
    _, call = session
    assert call("handoff_to_human", reason="other", summary="help")["error"]["code"] == \
        "INVALID_INPUT"


def test_model_cannot_confirm_within_the_same_turn(clean, settings):
    """End to end through the loop: the model tries to skip the customer's confirmation."""

    def confirm_immediately(messages):
        proposal = json.loads(messages[-1]["content"][0]["content"])
        return tool_call("create_return_request",
                         {**TEE_RETURN, "confirmation_token": proposal["confirmation_token"]})

    model = ScriptedModel([
        tool_call("get_order_status", LUCIA),
        tool_call("create_return_request", TEE_RETURN),
        confirm_immediately,
        text("Necesito tu confirmación: ¿devuelvo la camiseta?"),
    ])
    agent = Agent(model=model, registry=build_registry(), settings=replace(settings),
                  db=clean)
    conv = Conversation()
    result = agent.run_turn(conv, "Quiero devolver la camiseta del pedido 1043, "
                                  "lucia.romero@example.com")
    codes = [c.error_code for c in result.tool_calls]
    assert codes[-1] == "CONFIRMATION_NEEDS_CUSTOMER_REPLY"
    assert _count(clean, "return_requests") == 0
