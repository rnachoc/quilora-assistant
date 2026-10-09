"""Store-agnostic behaviour: profile, delivery estimates, sizes, Shopify import, policy
consistency, promotions, and a full run on a second (Spanish-language) shop.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
import pytest

from quilora.agent.guardrails import check_output
from quilora.config import Settings
from quilora.db import Database, migrate
from quilora.domain.delivery import add_business_days, estimate_window
from quilora.domain.sizes import canonical_size, match_size, size_sort_key
from quilora.importers.shopify import convert_feed, extract_material, guess_gender
from quilora.search.chunking import load_policies, parse_policy
from quilora.seed import load_all
from quilora.store.consistency import check
from quilora.store.profile import load_profile
from quilora.tools import build_registry
from quilora.tools.base import SessionState, ToolContext
from tests.conftest import _db_url

FIXTURES = Path(__file__).parent / "fixtures"
SPANISH_STORE = FIXTURES / "spanish_store"
MADRID = ZoneInfo("Europe/Madrid")


# --- store profile ----------------------------------------------------------------------

def test_demo_profile_loads_and_resolves_zones():
    store = Settings().store
    assert store.name == "Quilora"
    assert store.zone_for("es").id == "es-mainland"
    assert store.zone_for("ES-CN").id == "es-canary-ceuta-melilla"
    assert store.zone_for("FR").id == "eu"          # EU macro
    assert store.zone_for("US") is None             # no catch-all zone: not shipped


def test_profile_warns_about_eu_withdrawal_rules():
    store = load_profile(str(SPANISH_STORE))
    assert any("never be cancelled" in w for w in store.warnings())
    assert store.zone_for("US").id == "world"       # catch-all "*"
    short = store.model_copy(update={"returns": store.returns.model_copy(
        update={"window_days": 7})})
    assert any("shorter than the EU 14-day" in w for w in short.warnings())


def test_only_active_promotions_are_listed():
    store = load_profile(str(SPANISH_STORE))
    assert [p.code for p in store.active_promotions(date(2026, 10, 1))] == ["BIENVENIDA10"]
    assert [p.code for p in store.active_promotions(date(2027, 1, 1))] == []


# --- delivery ---------------------------------------------------------------------------

def test_business_days_skip_weekends_and_holidays():
    friday = date(2026, 10, 9)
    assert add_business_days(friday, 1, {date(2026, 10, 12)}) == date(2026, 10, 13)
    assert add_business_days(friday, 0, set()) == friday


def test_cutoff_moves_processing_to_next_business_day():
    before = estimate_window(ordered_at=datetime(2026, 10, 1, 10, tzinfo=MADRID),
                             processing_business_days=(0, 1), transit_business_days=(2, 4),
                             holidays=set(), cutoff_hour=14)
    after = estimate_window(ordered_at=datetime(2026, 10, 9, 15, tzinfo=MADRID),
                            processing_business_days=(0, 1), transit_business_days=(2, 4),
                            holidays={date(2026, 10, 12)}, cutoff_hour=14)
    assert before.arrives_between == (date(2026, 10, 5), date(2026, 10, 8))
    assert after.processing_starts == date(2026, 10, 13)  # Fri after cut-off, Mon holiday


# --- sizes ------------------------------------------------------------------------------

@pytest.mark.parametrize("label, canon", [
    ("xxl", "2XL"), ("2XL", "2XL"), ("Talla única", "ONE SIZE"), ("EU 38", "38"),
    ("XXS", "2XS"), ("m", "M"),
])
def test_canonical_sizes(label, canon):
    assert canonical_size(label) == canon


def test_size_matching_and_ordering():
    assert match_size("XXL", ["S", "M", "2XL"]) == "2XL"
    assert match_size("XS", ["S", "M"]) is None
    assert sorted(["4XL", "M", "2XS", "XL", "S"], key=size_sort_key) == \
        ["2XS", "S", "M", "XL", "4XL"]


# --- policy chunking and consistency ----------------------------------------------------

def test_chunker_accepts_unstructured_policies():
    chunks = load_policies(SPANISH_STORE / "policies")
    ids = [c.id for c in chunks]
    assert "DEVOLUCIONES-1" in ids                     # no headings: numbered parts
    assert any(c.section_title == "Plazos de entrega" for c in chunks)  # unnumbered "##"
    assert all(len(c.content.split()) <= 80 for c in chunks)


def test_long_sections_are_split_into_parts():
    body = " ".join(f"Sentence number {i} is here." for i in range(60))
    chunks = parse_policy(f"# Big\n<!-- doc_id: BIG -->\n## 1. Long\n{body}\n")
    assert [c.id for c in chunks][:2] == ["BIG-1-1", "BIG-1-2"]
    assert {c.section_no for c in chunks} == {1}


def test_consistency_check_finds_contradictions():
    store = load_profile(str(SPANISH_STORE))
    findings = check(store, load_policies(SPANISH_STORE / "policies"))
    by_fact = {(f.fact, f.value) for f in findings}
    assert ("return_window_days", 14) in by_fact       # 30 vs 14 days
    assert ("processing_business_days", 10) in by_fact  # "3 a 10" vs profile [1, 3]
    assert not any(f.fact == "refund_days" for f in findings)  # "catorce días" == 14


def test_demo_store_policies_are_consistent():
    store = Settings().store
    from quilora.paths import DATA_DIR
    assert check(store, load_policies(DATA_DIR / "policies")) == []


# --- Shopify import ---------------------------------------------------------------------

def _feed():
    return json.loads((FIXTURES / "shopify_products.json").read_text())


def test_shopify_conversion():
    products = {p["id"]: p for p in convert_feed(_feed(), domain="mare-demo.example",
                                                 strip_title_prefix=True)}
    assert set(products) == {"vestido-midi-lino-brisa", "chaqueta-acolchada-olivo",
                             "mocasin-clasico-ebano"}  # product without variants skipped
    dress = products["vestido-midi-lino-brisa"]
    assert dress["name"] == "Vestido Midi de Lino Brisa"
    assert dress["material"] == "55% lino, 45% algodón"
    assert dress["compare_at_price_eur"] == 79.90 and dress["gender"] == "women"
    assert dress["url"] == "https://mare-demo.example/products/vestido-midi-lino-brisa"
    assert [v["available"] for v in dress["variants"]] == [True, False, True]
    jacket = products["chaqueta-acolchada-olivo"]
    assert jacket["material"] is None                  # never guessed
    assert len({v["sku"] for v in jacket["variants"]}) == 2   # SKUs generated when empty
    shoe = products["mocasin-clasico-ebano"]
    assert shoe["category"] == "other" and shoe["gender"] == "men"
    assert shoe["compare_at_price_eur"] is None        # equal price is not a discount


def test_material_and_gender_heuristics():
    assert extract_material("Tejido suave. 95% cotton 5% elastane") == "95% cotton, 5% elastane"
    assert extract_material("Estampado de cachemir") is None
    assert guess_gender("unisex básico") == "unisex"


# --- guardrail with public promotions ---------------------------------------------------

def test_public_codes_pass_the_output_guard_only_when_a_tool_returned_them():
    reply = "Tienes el código BIENVENIDA10 con un 10% de descuento."
    assert not check_output(reply, grounding_text='{"code": "BIENVENIDA10"}', lang="es").blocked
    assert check_output(reply, grounding_text="", lang="es").blocked


# --- end to end on a second shop (own schema, Spanish search) ---------------------------

@pytest.fixture()
def spanish_shop(database, tmp_path):
    store_dir = tmp_path / "store"
    shutil.copytree(SPANISH_STORE, store_dir)
    (store_dir / "generated").mkdir()
    (store_dir / "generated" / "products.json").write_text(json.dumps(
        convert_feed(_feed(), strip_title_prefix=True), ensure_ascii=False))
    schema = "shop_mare_test"
    with psycopg.connect(_db_url()) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE; CREATE SCHEMA {schema}")
    with psycopg.connect(_db_url(), options=f"-c search_path={schema},public") as conn:
        migrate(conn)
        load_all(conn, store_dir)
    db = Database(_db_url(), max_size=2, search_path=schema)
    settings = Settings(database_url=_db_url(), store_today=date(2026, 10, 1),
                        store_dir=str(store_dir))
    yield db, settings
    db.close()
    with psycopg.connect(_db_url()) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


def test_second_shop_end_to_end(spanish_shop):
    db, settings = spanish_shop
    registry = build_registry(settings.store)
    ctx = ToolContext(db=db, settings=settings, state=SessionState(), session_id="t",
                      turn_index=1)

    def call(name, **args):
        return json.loads(registry.execute(name, args, ctx).content())

    # Tool descriptions speak about this shop and its catalog language.
    search_def = next(d for d in registry.definitions() if d["name"] == "search_products")
    assert "Maré Demo" in search_def["description"] and "Spanish" in search_def["description"]

    # Spanish stemming: "vestidos" finds "Vestido"; on_sale filter; size alias XXL.
    found = call("search_products", query="vestidos de lino", size="XXL")
    assert found["results"][0]["product_id"] == "vestido-midi-lino-brisa"
    assert found["results"][0]["discount_pct"] == 50
    assert call("search_products", on_sale=True)["count"] == 1

    stock = call("check_stock", product_id="vestido-midi-lino-brisa", size="m")
    assert stock["variants"][0]["availability"] == "out_of_stock"
    assert stock["variants"][0]["color"] == "Arena"

    jacket = call("get_product", product_id="chaqueta-acolchada-olivo")
    assert set(jacket["not_published"]) >= {"material", "care", "size_chart"}

    no_chart = call("get_size_recommendation", product_id="chaqueta-acolchada-olivo",
                    height_cm=165, weight_kg=58)
    assert no_chart["error"]["code"] == "NO_SIZE_CHART"  # no own chart, no store fallback

    delivery = call("estimate_delivery", destination="US")
    assert delivery["zone"] == "Resto del mundo"
    assert "separate parcels" in " ".join(delivery["notes"])

    promos = call("get_active_promotions")
    assert [p["code"] for p in promos["promotions"]] == ["BIENVENIDA10"]

    policies = call("search_policies", query="plazo de devolución")
    assert policies["results"][0]["policy_id"] == "DEVOLUCIONES-1"


def test_settings_store_dir_switches_profile(tmp_path):
    shutil.copytree(SPANISH_STORE, tmp_path / "s")
    settings = replace(Settings(), store_dir=str(tmp_path / "s"))
    assert settings.store.name == "Maré Demo"
    assert settings.now().tzinfo is not None
