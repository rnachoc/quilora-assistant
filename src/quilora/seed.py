"""Create the schema and load the synthetic dataset.

Usage:
    python -m quilora.seed            # migrate + (re)load all data
    python -m quilora.seed --reset-writes   # only clear returns/tickets/sessions (eval runs)
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from quilora.config import load_settings
from quilora.db import migrate
from quilora.search.chunking import load_policies

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
STORE_TZ = ZoneInfo("Europe/Madrid")

DATA_TABLES = [
    "order_items", "orders", "customers", "product_variants", "products", "size_charts",
    "policy_chunks",
]
# Tables written by the assistant at runtime (created by later migrations).
WRITE_TABLES = ["return_requests", "support_tickets", "audit_log", "chat_sessions"]


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value).replace(tzinfo=STORE_TZ) if value else None


def _existing(conn: psycopg.Connection, tables: list[str]) -> list[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()
    present = {r[0] for r in rows}
    return [t for t in tables if t in present]


def reset_writes(conn: psycopg.Connection) -> None:
    tables = _existing(conn, WRITE_TABLES)
    if tables:
        conn.execute(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")


def load_all(conn: psycopg.Connection) -> dict[str, int]:
    gen = DATA_DIR / "generated"
    charts = json.loads((gen / "size_charts.json").read_text())
    products = json.loads((gen / "products.json").read_text())
    customers = json.loads((gen / "customers.json").read_text())
    orders = json.loads((gen / "orders.json").read_text())
    chunks = load_policies(DATA_DIR / "policies")

    tables = _existing(conn, WRITE_TABLES + DATA_TABLES)
    conn.execute(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")

    with conn.cursor() as cur:
        for c in charts:
            cur.execute(
                "INSERT INTO size_charts (id, name, garment_type, gender, sizes, size_order)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (c["id"], c["name"], c["garment_type"], c["gender"], json.dumps(c["sizes"]),
                 list(c["sizes"].keys())),
            )
        for p in products:
            cur.execute(
                "INSERT INTO products (id, name, category, gender, description, material, fit,"
                " price_eur, size_chart_id, care, final_sale)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (p["id"], p["name"], p["category"], p["gender"], p["description"], p["material"],
                 p["fit"], p["price_eur"], p["size_chart_id"], p["care"], p["final_sale"]),
            )
            cur.executemany(
                "INSERT INTO product_variants (sku, product_id, color, size, stock)"
                " VALUES (%s, %s, %s, %s, %s)",
                [(v["sku"], p["id"], v["color"], v["size"], v["stock"]) for v in p["variants"]],
            )
        cur.executemany(
            "INSERT INTO customers (id, full_name, email, city, country, preferred_language)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            [(c["id"], c["full_name"], c["email"], c["city"], c["country"],
              c["preferred_language"]) for c in customers],
        )
        for o in orders:
            cur.execute(
                "INSERT INTO orders (id, customer_id, status, created_at, shipped_at, delivered_at,"
                " estimated_delivery, carrier, tracking_code, shipping_city, shipping_country,"
                " delivery_notes, subtotal_eur, shipping_eur, total_eur)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (o["id"], o["customer_id"], o["status"], _ts(o["created_at"]),
                 _ts(o["shipped_at"]), _ts(o["delivered_at"]), o["estimated_delivery"],
                 o["carrier"], o["tracking_code"], o["shipping_city"], o["shipping_country"],
                 o["delivery_notes"], o["subtotal_eur"], o["shipping_eur"], o["total_eur"]),
            )
            cur.executemany(
                "INSERT INTO order_items (order_id, line_no, sku, product_id, product_name, color,"
                " size, quantity, unit_price_eur) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [(o["id"], i["line_no"], i["sku"], i["product_id"], i["product_name"], i["color"],
                  i["size"], i["quantity"], i["unit_price_eur"]) for i in o["items"]],
            )
        cur.executemany(
            "INSERT INTO policy_chunks (id, doc_id, doc_title, section_no, section_title, content)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            [(c.id, c.doc_id, c.doc_title, c.section_no, c.section_title, c.content)
             for c in chunks],
        )

    return {
        "size_charts": len(charts),
        "products": len(products),
        "variants": sum(len(p["variants"]) for p in products),
        "customers": len(customers),
        "orders": len(orders),
        "policy_chunks": len(chunks),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset-writes", action="store_true",
                        help="only clear tables written by the assistant")
    args = parser.parse_args()
    settings = load_settings()
    with psycopg.connect(settings.database_url) as conn:
        applied = migrate(conn)
        if applied:
            print(f"Applied migrations: {', '.join(applied)}")
        if args.reset_writes:
            reset_writes(conn)
            print("Cleared runtime tables.")
            return
        counts = load_all(conn)
    print("Loaded: " + ", ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
