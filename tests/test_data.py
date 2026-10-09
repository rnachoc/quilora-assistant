"""Phase 1: the synthetic dataset is deterministic and contains the scenarios evals rely on.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from quilora.search.chunking import load_policies, parse_policy

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "data" / "generated"


def _load(name: str):
    return json.loads((GEN / name).read_text())


def test_generator_is_deterministic(tmp_path):
    before = {f.name: f.read_text() for f in GEN.glob("*.json")}
    subprocess.run([sys.executable, str(ROOT / "data" / "generate.py")], check=True,
                   capture_output=True)
    after = {f.name: f.read_text() for f in GEN.glob("*.json")}
    assert before == after


def test_catalog_size_and_unique_keys():
    products = _load("products.json")
    assert 60 <= len(products) <= 100
    assert len({p["id"] for p in products}) == len(products)
    assert len({p["name"] for p in products}) == len(products)
    skus = [v["sku"] for p in products for v in p["variants"]]
    assert len(skus) == len(set(skus))


def test_no_real_customer_emails():
    for c in _load("customers.json"):
        assert c["email"].endswith("@example.com")


def test_scenarios_used_by_evals_exist():
    products = {p["id"]: p for p in _load("products.json")}
    orders = {o["id"]: o for o in _load("orders.json")}

    linen = [p for p in products.values() if "Linen Midi Dress" in p["name"]]
    assert sum(p["price_eur"] < 60 for p in linen) >= 2
    assert any(p["price_eur"] >= 60 for p in linen)

    order = orders[1043]
    assert order["status"] == "delivered"
    assert any(i["product_id"].startswith("QL-TEE") for i in order["items"])
    assert "SYSTEM OVERRIDE" in orders[1046]["delivery_notes"]
    assert 25 <= len(orders) <= 35


def test_policies_chunk_into_numbered_sections():
    chunks = load_policies(ROOT / "data" / "policies")
    ids = [c.id for c in chunks]
    assert "RET-1" in ids and "SHP-2" in ids and "PAY-3" in ids
    assert len(ids) == len(set(ids))
    # Small embedding models truncate long inputs: keep sections short.
    assert max(len(c.content.split()) for c in chunks) <= 80


def test_parse_policy_citation():
    md = "# Returns Policy\n<!-- doc_id: RET -->\n\n## 1. Return window\nThirty days.\n"
    (chunk,) = parse_policy(md)
    assert chunk.id == "RET-1"
    assert chunk.citation == "Returns Policy §1 (Return window)"


def test_seed_loads_database(database):
    with database.connection() as conn:
        counts = conn.execute(
            "SELECT (SELECT count(*) FROM products) AS products,"
            " (SELECT count(*) FROM orders) AS orders,"
            " (SELECT count(*) FROM policy_chunks) AS chunks"
        ).fetchone()
    assert counts["products"] == len(_load("products.json"))
    assert counts["orders"] == len(_load("orders.json"))
    assert counts["chunks"] > 30
