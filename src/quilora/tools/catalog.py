"""Catalog tools: search_products, get_product, check_stock, get_size_recommendation.

Written for any online fashion shop, not one catalog: free-form product IDs and categories,
tags and collections, sale prices, sizes written in different ways (XXL / 2XL), optional
material, care and size chart, and availability with or without unit counts (public feeds
such as Shopify's only say whether a variant is available).

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from quilora.domain.sizes import equivalent_labels, match_size, size_sort_key
from quilora.domain.sizing import Measurements, MissingMeasurement, recommend
from quilora.tools.base import ToolContext, ToolError, ToolSpec

Gender = Literal["women", "men", "unisex"]

LOW_STOCK_THRESHOLD = 3
# Shop IDs vary (QL-TRS-001, Shopify handles, numeric IDs). Anything else is rejected
# before it reaches SQL.
PRODUCT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
# A variant can be sold if the shop marks it available and, when counts exist, has units.
IN_STOCK_SQL = "(v.available AND coalesce(v.stock > 0, true))"
OPTIONAL_INFO = ("material", "care", "fit")


def availability(stock: int | None, available: bool = True) -> str:
    """Customers see levels, not raw warehouse counts (see ADR 0006)."""
    if not available or (stock is not None and stock <= 0):
        return "out_of_stock"
    if stock is not None and stock <= LOW_STOCK_THRESHOLD:
        return "low_stock"
    return "in_stock"


def in_stock(v: dict) -> bool:
    """True if a variant row can be sold now."""
    return availability(v["stock"], v["available"]) != "out_of_stock"


def discount_pct(price, compare_at) -> int | None:
    """Discount computed by code from the shop's compare-at price; never estimated."""
    if compare_at is None or float(compare_at) <= float(price):
        return None
    return round(100 * (1 - float(price) / float(compare_at)))


def _variant_view(v: dict) -> dict:
    """Customer-facing view of a variant: availability level, units only when low."""
    view = {"color": v["color"], "size": v["size"],
            "availability": availability(v["stock"], v["available"])}
    if view["availability"] == "low_stock":
        view["units_left"] = v["stock"]  # "only 2 left" is useful and common in shops
    return view


def _price_view(p: dict) -> dict:
    """Price, previous price and discount, all from data."""
    pct = discount_pct(p["price_eur"], p["compare_at_price_eur"])
    view = {"price_eur": p["price_eur"], "on_sale": pct is not None}
    if pct is not None:
        view["compare_at_price_eur"] = p["compare_at_price_eur"]
        view["discount_pct"] = pct
    return view


class _Input(BaseModel):
    """Base for tool inputs: unknown fields are rejected and strings are trimmed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProductRef(_Input):
    """Input that identifies one product by the shop's own product ID."""

    product_id: str = Field(description="Product ID exactly as returned by search_products.")

    @field_validator("product_id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        """Reject IDs with spaces or symbols (they never come from search results)."""
        if not PRODUCT_ID_PATTERN.match(value):
            raise ValueError("not a valid product ID; use search_products to find IDs")
        return value


def _load_chart(conn, chart_id: str | None) -> dict | None:
    """Load a size chart by ID, or None."""
    if not chart_id:
        return None
    return conn.execute("SELECT id, garment_type, gender, size_order, sizes FROM size_charts"
                        " WHERE id = %s", (chart_id,)).fetchone()


def _load_product(ctx: ToolContext, product_id: str) -> dict:
    """Load a product, its variants and the size chart to use (own or store fallback)."""
    with ctx.db.connection() as conn:
        product = conn.execute("SELECT * FROM products WHERE lower(id) = lower(%s)",
                               (product_id,)).fetchone()
        if product is None:
            raise ToolError("PRODUCT_NOT_FOUND", f"No product with ID {product_id}.",
                            hint="Use search_products to find the right product ID.")
        variants = conn.execute(
            "SELECT color, size, stock, available FROM product_variants WHERE product_id = %s",
            (product["id"],)).fetchall()
        chart, source = _load_chart(conn, product["size_chart_id"]), "product"
        if chart is None:
            fallback = ctx.settings.store.catalog.fallback_size_charts.get(product["gender"])
            chart, source = _load_chart(conn, fallback), "store_general_guide"
    product["variants"] = sorted(variants, key=lambda v: (v["color"], size_sort_key(v["size"])))
    product["sizes"] = sorted({v["size"] for v in variants}, key=size_sort_key)
    product["chart"] = chart
    product["chart_source"] = source if chart else None
    return product


# --------------------------------------------------------------------------- search_products

class SearchProductsInput(_Input):
    """Input of search_products: keywords and/or filters."""

    query: str | None = Field(
        default=None, max_length=100,
        description="Search keywords in {catalog_language} (translate the customer's words "
                    "if needed), e.g. product type, fabric, style or print. Optional when a "
                    "category, collection or on_sale is given.")
    category: str | None = Field(default=None, max_length=50,
                                 description="Product category as the shop names it.")
    collection: str | None = Field(default=None, max_length=80,
                                   description="Shop collection name, e.g. a season or 'Sale'.")
    gender: Gender | None = Field(default=None, description="Department filter.")
    color: str | None = Field(default=None, max_length=40,
                              description="Colour in {catalog_language}, e.g. a basic colour "
                                          "name; partial matches count.")
    size: str | None = Field(default=None, max_length=12,
                             description="Size label, e.g. 'M', 'XXL' or '38'.")
    max_price_eur: float | None = Field(default=None, gt=0, description="Maximum price in EUR.")
    on_sale: bool | None = Field(default=None,
                                 description="True to return only discounted products.")
    in_stock_only: bool = Field(default=True,
                                description="Only products available in the requested "
                                            "colour/size (or any variant if none given).")
    limit: int = Field(default=5, ge=1, le=10, description="Maximum results (1-10).")

    @model_validator(mode="after")
    def _needs_something(self):
        """Refuse searches with no keywords and no narrowing filter."""
        if not (self.query or self.category or self.collection or self.on_sale):
            raise ValueError("give a query, a category, a collection or on_sale=true")
        return self


def _or_query(text: str) -> str:
    """Build an OR tsquery from the words of a query (fallback pass)."""
    words = re.findall(r"[^\W\d_]+", text.lower())
    return " | ".join(w for w in words if len(w) > 1)


def search_products(ctx: ToolContext, args: SearchProductsInput) -> dict:
    """Handler: search the catalog with filters, falling back to a partial match."""
    variant_filter = ["v.product_id = p.id"]
    params: dict = {"category": args.category, "collection": args.collection,
                    "gender": args.gender, "max_price": args.max_price_eur,
                    "on_sale": args.on_sale, "limit": args.limit,
                    "cfg": ctx.settings.store.catalog.search_config}
    if args.color:
        variant_filter.append("v.color ILIKE '%%' || %(color)s || '%%'")
        params["color"] = args.color
    if args.size:
        variant_filter.append("upper(v.size) = ANY(%(sizes)s)")
        params["sizes"] = equivalent_labels(args.size)
    if args.in_stock_only:
        variant_filter.append(IN_STOCK_SQL)
    where = " AND ".join(variant_filter)
    exists = f"EXISTS (SELECT 1 FROM product_variants v WHERE {where})"  # noqa: S608

    def run(tsquery_sql: str | None, query_text: str | None) -> list[dict]:
        """One search pass; tsquery_sql is a fixed SQL fragment, the text is a parameter."""
        rank = f"ts_rank(p.search_tsv, {tsquery_sql})" if tsquery_sql else "0"
        match = f"AND p.search_tsv @@ {tsquery_sql}" if tsquery_sql else ""
        # Only fixed SQL fragments are interpolated; all values go through parameters.
        sql = f"""
            SELECT p.id, p.name, p.category, p.gender, p.price_eur, p.compare_at_price_eur,
                   p.material, p.fit, p.final_sale, p.url, {rank} AS rank,
                   (SELECT array_agg(DISTINCT v.color ORDER BY v.color) FROM product_variants v
                     WHERE v.product_id = p.id AND {IN_STOCK_SQL}) AS colors_in_stock,
                   (SELECT array_agg(DISTINCT v.size) FROM product_variants v
                     WHERE v.product_id = p.id AND {IN_STOCK_SQL}) AS sizes_in_stock
              FROM products p
             WHERE (%(category)s::text IS NULL OR p.category ILIKE %(category)s)
               AND (%(collection)s::text IS NULL OR EXISTS (
                      SELECT 1 FROM unnest(p.collections) c WHERE c ILIKE %(collection)s))
               AND (%(gender)s::text IS NULL OR p.gender = %(gender)s)
               AND (%(max_price)s::numeric IS NULL OR p.price_eur <= %(max_price)s)
               AND (%(on_sale)s::boolean IS NOT TRUE
                    OR coalesce(p.compare_at_price_eur > p.price_eur, false))
               AND {exists}
               {match}
             ORDER BY rank DESC, p.price_eur ASC
             LIMIT %(limit)s"""  # noqa: S608
        with ctx.db.connection() as conn:
            return conn.execute(sql, {**params, "q": query_text}).fetchall()

    match_quality = "all_terms"
    if args.query:
        rows = run("websearch_to_tsquery(%(cfg)s::regconfig, %(q)s)", args.query)
        if not rows and _or_query(args.query):
            # Second pass: any of the words. Tell the model results are a partial match.
            rows = run("to_tsquery(%(cfg)s::regconfig, %(q)s)", _or_query(args.query))
            match_quality = "some_terms"
    else:
        rows = run(None, None)
        match_quality = "filters_only"

    results = []
    for r in rows:
        item = {"product_id": r["id"], "name": r["name"], "category": r["category"],
                "gender": r["gender"], **_price_view(r), "material": r["material"],
                "fit": r["fit"], "final_sale": r["final_sale"],
                "colors_in_stock": r["colors_in_stock"] or [],
                "sizes_in_stock": sorted(r["sizes_in_stock"] or [], key=size_sort_key)}
        if r["url"]:
            item["url"] = r["url"]
        results.append(item)
    payload: dict = {"count": len(results), "match": match_quality, "results": results}
    if not results:
        with ctx.db.connection() as conn:
            categories = [row["category"] for row in conn.execute(
                "SELECT DISTINCT category FROM products ORDER BY 1").fetchall()]
        payload["known_categories"] = categories
        payload["hint"] = ("No products match. Tell the customer, and suggest relaxing a filter "
                           "(price, colour, size) or one of the known categories.")
    return payload


# --------------------------------------------------------------------------- get_product

def get_product(ctx: ToolContext, args: ProductRef) -> dict:
    """Handler: full product details with an availability matrix and what is not published."""
    p = _load_product(ctx, args.product_id)
    by_colour: dict[str, dict[str, str]] = {}
    for v in p["variants"]:
        by_colour.setdefault(v["color"], {})[v["size"]] = availability(v["stock"], v["available"])
    missing = [f for f in OPTIONAL_INFO if not p[f]]
    if p["chart_source"] != "product":
        missing.append("size_chart")
    view = {
        "product_id": p["id"], "name": p["name"], "category": p["category"],
        "gender": p["gender"], **_price_view(p), "description": p["description"],
        "material": p["material"], "fit": p["fit"], "care": p["care"],
        "final_sale": p["final_sale"], "tags": p["tags"], "collections": p["collections"],
        "sizes": p["sizes"], "availability_by_color": by_colour,
    }
    for optional in ("url", "model_info"):
        if p[optional]:
            view[optional] = p[optional]
    if missing:
        view["not_published"] = missing
        view["hint"] = ("The shop does not publish these details for this product. Say so "
                        "plainly; never guess them from the name, tags or photos.")
    return view


# --------------------------------------------------------------------------- check_stock

class CheckStockInput(ProductRef):
    """Input of check_stock: product plus optional colour and size."""

    color: str | None = Field(default=None, max_length=40,
                              description="Colour in {catalog_language}. Omit for all colours.")
    size: str | None = Field(default=None, max_length=12,
                             description="Size label, e.g. 'M' or 'XXL'. Omit for all sizes.")


def check_stock(ctx: ToolContext, args: CheckStockInput) -> dict:
    """Handler: availability for a colour/size, with alternatives when sold out."""
    p = _load_product(ctx, args.product_id)
    variants = p["variants"]
    colours = sorted({v["color"] for v in variants})

    colour = None
    if args.color:
        wanted = args.color.lower()
        exact = [c for c in colours if c.lower() == wanted]
        partial = [c for c in colours if wanted in c.lower()]
        matches = exact or partial
        if not matches:
            raise ToolError("UNKNOWN_COLOR", f"{p['name']} does not come in {args.color!r}.",
                            hint="Tell the customer which colours exist (translate them).",
                            details={"available_colors": colours})
        if len(matches) > 1:
            raise ToolError("AMBIGUOUS_COLOR", f"{args.color!r} matches several colours.",
                            hint="Ask the customer which one they mean.",
                            details={"matching_colors": matches})
        colour = matches[0]

    size = None
    if args.size:
        size = match_size(args.size, p["sizes"])
        if size is None:
            raise ToolError("UNKNOWN_SIZE", f"{p['name']} is not made in size {args.size!r}.",
                            hint="Tell the customer the available sizes.",
                            details={"available_sizes": p["sizes"]})

    selected = [v for v in variants
                if (colour is None or v["color"] == colour) and (size is None or v["size"] == size)]
    payload: dict = {"product_id": p["id"], "name": p["name"], **_price_view(p),
                     "variants": [_variant_view(v) for v in selected]}
    if colour and size and not any(in_stock(v) for v in selected):
        payload["alternatives"] = {
            "same_size_other_colors": [v["color"] for v in variants
                                       if v["size"] == size and in_stock(v)],
            "same_color_other_sizes": [v["size"] for v in variants
                                       if v["color"] == colour and in_stock(v)],
        }
    return payload


# --------------------------------------------------------------------------- size recommendation

class SizeRecommendationInput(ProductRef):
    """Input of get_size_recommendation: product plus body data."""

    height_cm: float | None = Field(default=None, ge=120, le=230,
                                    description="Height in cm (1,68 m -> 168).")
    weight_kg: float | None = Field(default=None, ge=30, le=250, description="Weight in kg.")
    chest_cm: float | None = Field(default=None, ge=50, le=200)
    waist_cm: float | None = Field(default=None, ge=40, le=200)
    hip_cm: float | None = Field(default=None, ge=50, le=200)
    foot_length_cm: float | None = Field(default=None, ge=15, le=35,
                                         description="Heel to longest toe, for shoes.")
    fit_preference: Literal["closer", "regular", "looser"] = "regular"


def get_size_recommendation(ctx: ToolContext, args: SizeRecommendationInput) -> dict:
    """Handler: run the sizing algorithm on the product's chart (or the store's general guide)."""
    p = _load_product(ctx, args.product_id)
    chart = p["chart"]
    if chart is None:
        raise ToolError(
            "NO_SIZE_CHART", f"There is no size information for {p['name']}.",
            hint="Tell the customer the shop does not publish a size guide for this item, list "
                 "the sizes it comes in, and offer a transfer to the team for advice.",
            details={"sizes": p["sizes"]})
    try:
        rec = recommend(
            garment_type=chart["garment_type"], chart_gender=chart["gender"],
            size_order=chart["size_order"], sizes=chart["sizes"],
            product_fit=p["fit"] or "regular",
            measurements=Measurements(args.height_cm, args.weight_kg, args.chest_cm,
                                      args.waist_cm, args.hip_cm, args.foot_length_cm),
            preference=args.fit_preference,
        )
    except MissingMeasurement as exc:
        raise ToolError("MISSING_MEASUREMENT", f"Need {exc} to recommend a size.",
                        hint="Ask the customer for it. For shoes ask for foot length in cm "
                             "(heel to longest toe).") from exc

    notes = list(rec.notes)
    confidence = rec.confidence
    if p["chart_source"] == "store_general_guide":
        confidence = "low"
        notes.append("This product has no size chart of its own; this uses the shop's general "
                     "size guide, so it is only an approximation.")
    label = match_size(rec.recommended_size, p["sizes"])
    if label is None:
        notes.append(f"Size {rec.recommended_size} is not made for this product.")
    alternative = match_size(rec.alternative_size, p["sizes"]) if rec.alternative_size else None

    return {
        "product_id": p["id"], "name": p["name"], "product_fit": p["fit"],
        "recommended_size": label or rec.recommended_size,
        "recommended_size_offered": label is not None,
        "alternative_size": alternative,
        "confidence": confidence, "basis": rec.basis, "size_chart": p["chart_source"],
        "measurements_used": rec.measurements_used, "notes": notes,
        "recommended_size_in_stock_colors": [v["color"] for v in p["variants"]
                                             if label and v["size"] == label and in_stock(v)],
        **({"model_info": p["model_info"]} if p["model_info"] else {}),
    }


# --------------------------------------------------------------------------- specs

SEARCH_PRODUCTS = ToolSpec(
    name="search_products",
    description=(
        "Search the {store_name} catalog. Use it whenever the customer looks for products, asks "
        "what exists or what is on sale, or mentions a budget, colour or size. Returns up to "
        "`limit` products with price (and previous price and discount when on sale), material "
        "when published and the colours/sizes currently available. The catalog is written in "
        "{catalog_language}: use that language for keywords and colours. Use get_product or "
        "check_stock for details of one product."
    ),
    input_model=SearchProductsInput,
    handler=search_products,
)

GET_PRODUCT = ToolSpec(
    name="get_product",
    description=(
        "Get full details of one product by ID: price and discount, description, material, "
        "fit and care when published, tags, sizes and an availability matrix by colour and "
        "size. `not_published` lists details the shop does not provide. Use it when the "
        "customer asks about a specific product found earlier."
    ),
    input_model=ProductRef,
    handler=get_product,
)

CHECK_STOCK = ToolSpec(
    name="check_stock",
    description=(
        "Check availability of a product for a colour and/or size. Returns availability levels "
        "(in_stock, low_stock with units_left, out_of_stock) and, when the requested "
        "combination is sold out, alternatives in other colours or sizes. Needs a product ID: "
        "if the customer has not identified the product yet, search first or ask which one."
    ),
    input_model=CheckStockInput,
    handler=check_stock,
)

GET_SIZE_RECOMMENDATION = ToolSpec(
    name="get_size_recommendation",
    description=(
        "Recommend a size for a specific product using its size chart (or the shop's general "
        "size guide when the product has none) and its fit. Accepts height and weight (an "
        "estimate with low confidence) and/or chest, waist and hip measurements in cm (more "
        "reliable); shoes need foot length. Always use this tool instead of guessing a size. "
        "Explain the confidence and notes to the customer."
    ),
    input_model=SizeRecommendationInput,
    handler=get_size_recommendation,
)
