"""Import a Shopify catalog (the public products.json feed or an Admin API export).

    python -m quilora.importers.shopify products.json --store-dir my_store \\
        --domain shop.example.com --strip-title-prefix

Writes `my_store/generated/products.json` in this project's catalog format, ready for
`STORE_DIR=my_store python -m quilora.seed`. What the feed does not contain stays empty
on purpose (material when not written as percentages, care, fit, size chart, stock
counts): the assistant then says the shop does not publish it instead of guessing.

Mapping:
  handle              -> product id (stable, URL-safe)
  title               -> name (optionally without a "BRAND | " prefix)
  product_type        -> category (lower-case; "other" if empty)
  tags                -> tags; department guessed from tags, type and title words
  options             -> colour and size, recognised by name in several languages
  variants            -> sku, colour, size, available (no unit counts in the public feed)
  price/compare_at    -> lowest variant price; previous price only if higher
  body_html           -> plain-text description; "95% cotton, 5% elastane" -> material

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import argparse
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

SIZE_OPTION_NAMES = {"size", "talla", "taille", "taglia", "größe", "grosse", "groesse",
                     "tamaño", "tamano", "maat", "storlek", "tamanho"}
COLOR_OPTION_NAMES = {"color", "colour", "colore", "couleur", "farbe", "kleur", "färg",
                      "farg", "cor"}
WOMEN_WORDS = {"mujer", "mujeres", "women", "woman", "womens", "dama", "femme", "donna",
               "ella", "señora", "frau", "damen", "mulher"}
MEN_WORDS = {"hombre", "hombres", "men", "man", "mens", "homme", "uomo", "él", "caballero",
             "herren", "homem"}
_COMPOSITION = re.compile(r"\b(\d{1,3})\s?%\s?([A-Za-zÀ-ÿ]+(?:\s(?!y\b|and\b)[A-Za-zÀ-ÿ]+)?)")
_BRAND_PREFIX = re.compile(r"^[^|]{1,40}\|\s*")


class _TextExtractor(HTMLParser):
    """Collect visible text from body_html, keeping paragraph breaks."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        """Block-level tags start a new line."""
        if tag in {"p", "br", "li", "div", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        """Keep visible text."""
        self.parts.append(data)


def html_to_text(body: str | None) -> str:
    """Strip tags and entities from Shopify's body_html."""
    if not body:
        return ""
    parser = _TextExtractor()
    parser.feed(body)
    text = html.unescape("".join(parser.parts))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def guess_gender(*texts: str) -> str:
    """Department from words in tags, product type and title; 'unisex' when unclear."""
    words = set(re.findall(r"[^\W\d_]+", " ".join(texts).lower()))
    women, men = bool(words & WOMEN_WORDS), bool(words & MEN_WORDS)
    if women and not men:
        return "women"
    if men and not women:
        return "men"
    return "unisex"


def extract_material(text: str) -> str | None:
    """'95% algodón, 5% elastano' style compositions only; anything vaguer is left empty."""
    found = [f"{pct}% {name.strip().lower()}" for pct, name in _COMPOSITION.findall(text)]
    return ", ".join(dict.fromkeys(found)) or None


def _tags(raw) -> list[str]:
    """Tags arrive as a list (JSON feed) or a comma-separated string (CSV/Admin)."""
    if isinstance(raw, str):
        raw = raw.split(",")
    return sorted({t.strip() for t in raw or [] if t and t.strip()})


def _option_positions(options: list[dict]) -> tuple[int | None, int | None]:
    """Which option (1-3) holds the colour and which the size."""
    color = size = None
    for i, option in enumerate(options or [], start=1):
        name = (option.get("name") or "").strip().lower()
        if name in SIZE_OPTION_NAMES and size is None:
            size = i
        elif name in COLOR_OPTION_NAMES and color is None:
            color = i
    return color, size


def convert_product(p: dict, *, domain: str | None = None,
                    strip_title_prefix: bool = False) -> dict:
    """Convert one Shopify product into this project's catalog format."""
    title = p["title"].strip()
    if strip_title_prefix:
        title = _BRAND_PREFIX.sub("", title)
    description = html_to_text(p.get("body_html"))
    tags = _tags(p.get("tags"))
    color_pos, size_pos = _option_positions(p.get("options", []))

    variants, seen_skus = [], set()
    for v in p.get("variants", []):
        color = v.get(f"option{color_pos}") if color_pos else None
        size = v.get(f"option{size_pos}") if size_pos else None
        sku = (v.get("sku") or "").strip() or f"{p['handle']}-{v['id']}"
        if sku in seen_skus:
            sku = f"{sku}-{v['id']}"
        seen_skus.add(sku)
        quantity = v.get("inventory_quantity")  # only present in Admin API exports
        variants.append({
            "sku": sku,
            "color": color or "default",
            "size": size or "ONE SIZE",
            "stock": quantity if isinstance(quantity, int) else None,
            "available": bool(v.get("available", True)),
        })

    prices = [float(v["price"]) for v in p.get("variants", []) if v.get("price")]
    compare = [float(v["compare_at_price"]) for v in p.get("variants", [])
               if v.get("compare_at_price")]
    price = min(prices) if prices else 0.0
    compare_at = max(compare) if compare and max(compare) > price else None

    return {
        "id": p["handle"],
        "name": title,
        "category": (p.get("product_type") or "other").strip().lower(),
        "gender": guess_gender(" ".join(tags), p.get("product_type") or "", title),
        "description": description[:4000] or title,
        "material": extract_material(description),
        "fit": None,
        "care": None,
        "size_chart_id": None,
        "final_sale": False,
        "price_eur": price,
        "compare_at_price_eur": compare_at,
        "tags": tags,
        "collections": [],
        "url": f"https://{domain}/products/{p['handle']}" if domain else None,
        "variants": variants,
    }


def convert_feed(feed, **options) -> list[dict]:
    """Convert a whole feed ({"products": [...]} or a plain list), skipping products
    without variants."""
    products = feed["products"] if isinstance(feed, dict) else feed
    return [convert_product(p, **options) for p in products if p.get("variants")]


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Import a Shopify products.json feed")
    parser.add_argument("feed", type=Path, help="products.json (public feed or Admin export)")
    parser.add_argument("--store-dir", type=Path, required=True,
                        help="store directory (with store.yaml and policies/)")
    parser.add_argument("--domain", help="shop domain, to build product URLs")
    parser.add_argument("--strip-title-prefix", action="store_true",
                        help='remove a "BRAND | " prefix from product titles')
    args = parser.parse_args()
    products = convert_feed(json.loads(args.feed.read_text(encoding="utf-8")),
                            domain=args.domain, strip_title_prefix=args.strip_title_prefix)
    out = args.store_dir / "generated"
    out.mkdir(parents=True, exist_ok=True)
    (out / "products.json").write_text(json.dumps(products, indent=2, ensure_ascii=False) + "\n",
                                       encoding="utf-8")
    missing = sum(1 for p in products if not p["material"])
    print(f"Imported {len(products)} products "
          f"({sum(len(p['variants']) for p in products)} variants) into {out}. "
          f"{missing} without a published composition.")


if __name__ == "__main__":
    main()
