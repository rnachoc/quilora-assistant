"""Phase 3: read-only tools against the seeded database."""

from __future__ import annotations

import json
import time

import pytest
from pydantic import BaseModel

from quilora.tools import build_registry
from quilora.tools.base import SessionState, ToolContext, ToolRegistry, ToolSpec


@pytest.fixture()
def ctx(database, settings):
    return ToolContext(db=database, settings=settings, state=SessionState(), session_id="test",
                       turn_index=1)


@pytest.fixture()
def registry():
    return build_registry()


def call(registry, ctx, name, **args):
    outcome = registry.execute(name, args, ctx)
    return outcome, json.loads(outcome.content())


# --- search_products --------------------------------------------------------------------

def test_linen_dresses_under_60(registry, ctx):
    outcome, data = call(registry, ctx, "search_products", query="linen dress",
                         max_price_eur=60, limit=10)
    assert not outcome.is_error
    names = {r["name"] for r in data["results"]}
    assert {"Garza Linen Midi Dress", "Brisa Linen Midi Dress", "Dalia Linen Midi Dress"} <= names
    assert all(r["price_eur"] <= 60 for r in data["results"])


def test_search_filters_by_size_and_colour_in_stock(registry, ctx):
    _, data = call(registry, ctx, "search_products", query="linen trousers", color="sand",
                   size="M", gender="women", limit=10)
    # QL-TRS-001 is sold out in sand/M, so it must not appear
    assert "QL-TRS-001" not in {r["product_id"] for r in data["results"]}


def test_search_needs_query_or_category(registry, ctx):
    outcome, data = call(registry, ctx, "search_products", color="black")
    assert outcome.is_error and data["error"]["code"] == "INVALID_INPUT"


def test_search_falls_back_to_partial_match(registry, ctx):
    _, data = call(registry, ctx, "search_products", query="linen spaceship")
    assert data["match"] == "some_terms" and data["count"] > 0


# --- get_product / check_stock ----------------------------------------------------------

def test_get_product_reports_levels_not_counts(registry, ctx):
    _, data = call(registry, ctx, "get_product", product_id="ql-trs-001")
    assert data["availability_by_color"]["sand"]["M"] == "out_of_stock"
    assert "stock" not in json.dumps(data["availability_by_color"]).replace("_stock", "")


def test_check_stock_black_m_available(registry, ctx):
    _, data = call(registry, ctx, "check_stock", product_id="QL-TRS-001", color="black", size="M")
    assert data["variants"] == [{"color": "black", "size": "M", "availability": "in_stock"}]


def test_check_stock_sold_out_suggests_alternatives(registry, ctx):
    _, data = call(registry, ctx, "check_stock", product_id="QL-TRS-001", color="sand", size="M")
    assert data["variants"][0]["availability"] == "out_of_stock"
    assert "black" in data["alternatives"]["same_size_other_colors"]


def test_low_stock_shows_units_left(registry, ctx):
    _, data = call(registry, ctx, "check_stock", product_id="QL-TEE-001", color="black", size="M")
    assert data["variants"][0] == {"color": "black", "size": "M", "availability": "low_stock",
                                   "units_left": 2}


def test_unknown_colour_lists_available_ones(registry, ctx):
    outcome, data = call(registry, ctx, "check_stock", product_id="QL-TRS-001", color="negro")
    assert data["error"]["code"] == "UNKNOWN_COLOR"
    assert "black" in data["error"]["details"]["available_colors"]


def test_unknown_product(registry, ctx):
    _, data = call(registry, ctx, "get_product", product_id="QL-XXX-999")
    assert data["error"]["code"] == "PRODUCT_NOT_FOUND"


def test_malformed_product_id_is_rejected_before_sql(registry, ctx):
    _, data = call(registry, ctx, "get_product", product_id="1; DROP TABLE products")
    assert data["error"]["code"] == "INVALID_INPUT"


# --- size recommendation ----------------------------------------------------------------

def test_size_for_the_trousers_from_the_brief(registry, ctx):
    _, data = call(registry, ctx, "get_size_recommendation", product_id="QL-TRS-001",
                   height_cm=168, weight_kg=60)
    assert data["recommended_size"] == "M"
    assert data["confidence"] == "low"
    assert "black" in data["recommended_size_in_stock_colors"]


def test_shoes_without_foot_length(registry, ctx):
    _, data = call(registry, ctx, "get_size_recommendation", product_id="QL-SHO-001",
                   height_cm=168, weight_kg=60)
    assert data["error"]["code"] == "MISSING_MEASUREMENT"


# --- get_order_status -------------------------------------------------------------------

def test_order_lookup_happy_path(registry, ctx):
    outcome, data = call(registry, ctx, "get_order_status", order_id="#1043",
                         email="Lucia.Romero@example.com")
    assert not outcome.is_error
    assert data["status"] == "delivered"
    assert data["customer_email_masked"] == "l***@example.com"
    tee = next(i for i in data["items"] if i["product_id"] == "QL-TEE-001")
    assert tee["return"]["eligible"] is True
    assert tee["return"]["return_deadline"] == "2026-10-20"
    assert ctx.state.verified_orders == {"1043": "lucia.romero@example.com"}


def test_wrong_email_and_missing_order_look_identical(registry, ctx):
    _, wrong_email = call(registry, ctx, "get_order_status", order_id=1043,
                          email="attacker@example.com")
    _, missing = call(registry, ctx, "get_order_status", order_id=9999,
                      email="lucia.romero@example.com")
    assert wrong_email == missing
    assert wrong_email["error"]["code"] == "ORDER_NOT_FOUND_OR_EMAIL_MISMATCH"
    assert ctx.state.verified_orders == {}


def test_lookup_locks_after_three_failures(registry, ctx):
    for _ in range(3):
        call(registry, ctx, "get_order_status", order_id=1043, email="x@example.com")
    _, data = call(registry, ctx, "get_order_status", order_id=1043,
                   email="lucia.romero@example.com")
    assert data["error"]["code"] == "VERIFICATION_LOCKED"


def test_customer_note_is_wrapped_as_untrusted(registry, ctx):
    _, data = call(registry, ctx, "get_order_status", order_id=1046,
                   email="mario.pastor@example.com")
    note = data["untrusted_customer_note"]
    assert "not instructions" in note["warning"]
    assert "SYSTEM OVERRIDE" in note["text"]


def test_delayed_order_is_flagged(registry, ctx):
    _, data = call(registry, ctx, "get_order_status", order_id=1049,
                   email="emma.fuentes@example.com")
    assert data["is_delayed"] is True


def test_expired_window(registry, ctx):
    _, data = call(registry, ctx, "get_order_status", order_id=1031,
                   email="lucia.romero@example.com")
    assert {i["return"]["reason"] for i in data["items"]} == {"window_expired"}


# --- registry behaviour -----------------------------------------------------------------

class _Empty(BaseModel):
    pass


def test_registry_unknown_tool_and_internal_errors(ctx):
    def boom(_ctx, _args):
        raise RuntimeError("secret internals")

    reg = ToolRegistry([ToolSpec("boom", "fails", _Empty, boom)])
    _, unknown = call(reg, ctx, "nope")
    assert unknown["error"]["code"] == "UNKNOWN_TOOL"
    outcome, data = call(reg, ctx, "boom")
    assert data["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in outcome.content()


def test_registry_timeout(ctx, settings):
    from dataclasses import replace

    def slow(_ctx, _args):
        time.sleep(1)
        return {}

    fast_ctx = ToolContext(db=ctx.db, settings=replace(settings, tool_timeout_s=0.1),
                           state=ctx.state, session_id="t", turn_index=1)
    reg = ToolRegistry([ToolSpec("slow", "sleeps", _Empty, slow)])
    _, data = call(reg, fast_ctx, "slow")
    assert data["error"]["code"] == "TIMEOUT" and data["error"]["retryable"] is True


def test_tool_definitions_are_compact_and_valid():
    for definition in build_registry().definitions():
        assert definition["description"]
        schema = definition["input_schema"]
        assert schema["type"] == "object"
        assert "title" not in schema
        assert schema.get("additionalProperties") is False
        assert "$ref" not in json.dumps(schema) and "$defs" not in schema
