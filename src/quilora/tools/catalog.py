"""Catalog tools: search_products, get_product, check_stock, get_size_recommendation."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from quilora.domain.sizing import Measurements, MissingMeasurement, recommend
from quilora.tools.base import ToolContext, ToolError, ToolSpec

Category = Literal["dresses", "tops", "t-shirts", "shirts", "trousers", "jeans", "skirts",
                   "knitwear", "jackets", "shoes", "accessories"]
Gender = Literal["women", "men", "unisex"]

LOW_STOCK_THRESHOLD = 3
PRODUCT_ID_PATTERN = re.compile(r"^QL-[A-Z]{3}-\d{3}$")


def availability(stock: int) -> str:
    """Customers see levels, not raw warehouse counts (see ADR 0006)."""
    if stock <= 0:
        return "out_of_stock"
    if stock <= LOW_STOCK_THRESHOLD:
        return "low_stock"
    return "in_stock"


def _variant_view(v: dict) -> dict:
    view = {"color": v["color"], "size": v["size"], "availability": availability(v["stock"])}
    if view["availability"] == "low_stock":
        view["units_left"] = v["stock"]  # "only 2 left" is useful and common in shops
    return view


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProductRef(_Input):
    product_id: str = Field(description="Quilora product ID, e.g. 'QL-TRS-001'.")

    @field_validator("product_id")
    @classmethod
    def _normalise_id(cls, value: str) -> str:
        value = value.upper()
        if not PRODUCT_ID_PATTERN.match(value):
            raise ValueError("must look like 'QL-ABC-123'; use search_products to find IDs")
        return value


def _load_product(ctx: ToolContext, product_id: str) -> dict:
    with ctx.db.connection() as conn:
        product = conn.execute(
            "SELECT p.*, sc.garment_type, sc.gender AS chart_gender, sc.size_order, sc.sizes"
            " FROM products p JOIN size_charts sc ON sc.id = p.size_chart_id WHERE p.id = %s",
            (product_id,),
        ).fetchone()
        if product is None:
            raise ToolError("PRODUCT_NOT_FOUND", f"No product with ID {product_id}.",
                            hint="Use search_products to find the right product ID.")
        product["variants"] = conn.execute(
            "SELECT color, size, stock FROM product_variants WHERE product_id = %s"
            " ORDER BY color, array_position(%s::text[], size)",
            (product_id, product["size_order"]),
        ).fetchall()
    return product


# --------------------------------------------------------------------------- search_products

class SearchProductsInput(_Input):
    query: str | None = Field(
        default=None, max_length=100,
        description="Search keywords IN ENGLISH (translate the customer's words), e.g. "
                    "'linen dress', 'black jeans'. Optional when a category is given.")
    category: Category | None = Field(default=None, description="Product category filter.")
    gender: Gender | None = Field(default=None, description="Department filter.")
    color: str | None = Field(default=None, max_length=30,
                              description="Colour IN ENGLISH, e.g. 'black', 'blue'.")
    size: str | None = Field(default=None, max_length=10,
                             description="Size label, e.g. 'M' or '38'.")
    max_price_eur: float | None = Field(default=None, gt=0, description="Maximum price in EUR.")
    in_stock_only: bool = Field(default=True,
                                description="Only products with stock in the requested "
                                            "colour/size (or any variant if none given).")
    limit: int = Field(default=5, ge=1, le=10, description="Maximum results (1-10).")

    @model_validator(mode="after")
    def _needs_query_or_category(self):
        if not self.query and not self.category:
            raise ValueError("give a query, a category, or both")
        return self


def _or_query(text: str) -> str:
    words = re.findall(r"[a-zA-Z]+", text.lower())
    return " | ".join(words)


def search_products(ctx: ToolContext, args: SearchProductsInput) -> dict:
    variant_filter = ["v.product_id = p.id"]
    params: dict = {"category": args.category, "gender": args.gender,
                    "max_price": args.max_price_eur, "limit": args.limit}
    if args.color:
        variant_filter.append("v.color ILIKE '%%' || %(color)s || '%%'")
        params["color"] = args.color
    if args.size:
        variant_filter.append("upper(v.size) = upper(%(size)s)")
        params["size"] = args.size
    if args.in_stock_only:
        variant_filter.append("v.stock > 0")
    where = " AND ".join(variant_filter)
    exists = f"EXISTS (SELECT 1 FROM product_variants v WHERE {where})"  # noqa: S608

    def run(tsquery_sql: str | None, query_text: str | None) -> list[dict]:
        rank = f"ts_rank(p.search_tsv, {tsquery_sql})" if tsquery_sql else "0"
        match = f"AND p.search_tsv @@ {tsquery_sql}" if tsquery_sql else ""
        # Only fixed SQL fragments are interpolated; all values go through parameters.
        sql = f"""
            SELECT p.id, p.name, p.category, p.gender, p.price_eur, p.material, p.fit,
                   p.final_sale, {rank} AS rank,
                   (SELECT array_agg(DISTINCT v.color ORDER BY v.color) FROM product_variants v
                     WHERE v.product_id = p.id AND v.stock > 0) AS colors_in_stock,
                   (SELECT array_agg(v.size ORDER BY array_position(sc.size_order, v.size))
                      FROM (SELECT DISTINCT size FROM product_variants
                             WHERE product_id = p.id AND stock > 0) v) AS sizes_in_stock
              FROM products p JOIN size_charts sc ON sc.id = p.size_chart_id
             WHERE (%(category)s::text IS NULL OR p.category = %(category)s)
               AND (%(gender)s::text IS NULL OR p.gender = %(gender)s)
               AND (%(max_price)s::numeric IS NULL OR p.price_eur <= %(max_price)s)
               AND {exists}
               {match}
             ORDER BY rank DESC, p.price_eur ASC
             LIMIT %(limit)s"""  # noqa: S608
        with ctx.db.connection() as conn:
            return conn.execute(sql, {**params, "q": query_text}).fetchall()

    match_quality = "all_terms"
    if args.query:
        rows = run("websearch_to_tsquery('english', %(q)s)", args.query)
        if not rows and _or_query(args.query):
            # Second pass: any of the words. Tell the model results are a partial match.
            rows = run("to_tsquery('english', %(q)s)", _or_query(args.query))
            match_quality = "some_terms"
    else:
        rows = run(None, None)
        match_quality = "filters_only"

    results = [
        {
            "product_id": r["id"],
            "name": r["name"],
            "category": r["category"],
            "gender": r["gender"],
            "price_eur": r["price_eur"],
            "material": r["material"],
            "fit": r["fit"],
            "final_sale": r["final_sale"],
            "colors_in_stock": r["colors_in_stock"] or [],
            "sizes_in_stock": r["sizes_in_stock"] or [],
        }
        for r in rows
    ]
    payload: dict = {"count": len(results), "match": match_quality, "results": results}
    if not results:
        payload["hint"] = ("No products match. Tell the customer, and suggest relaxing a filter "
                           "(price, colour, size) or a related category.")
    return payload


# --------------------------------------------------------------------------- get_product

def get_product(ctx: ToolContext, args: ProductRef) -> dict:
    p = _load_product(ctx, args.product_id)
    by_colour: dict[str, dict[str, str]] = {}
    for v in p["variants"]:
        by_colour.setdefault(v["color"], {})[v["size"]] = availability(v["stock"])
    return {
        "product_id": p["id"],
        "name": p["name"],
        "category": p["category"],
        "gender": p["gender"],
        "price_eur": p["price_eur"],
        "description": p["description"],
        "material": p["material"],
        "fit": p["fit"],
        "care": p["care"],
        "final_sale": p["final_sale"],
        "sizes": p["size_order"],
        "availability_by_color": by_colour,
    }


# --------------------------------------------------------------------------- check_stock

class CheckStockInput(ProductRef):
    color: str | None = Field(default=None, max_length=30,
                              description="Colour IN ENGLISH, e.g. 'black'. Omit for all colours.")
    size: str | None = Field(default=None, max_length=10,
                             description="Size label, e.g. 'M'. Omit for all sizes.")


def check_stock(ctx: ToolContext, args: CheckStockInput) -> dict:
    p = _load_product(ctx, args.product_id)
    variants = p["variants"]
    colours = sorted({v["color"] for v in variants})
    sizes = p["size_order"]

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
        size = next((s for s in sizes if s.upper() == args.size.upper()), None)
        if size is None:
            raise ToolError("UNKNOWN_SIZE", f"{p['name']} is not made in size {args.size!r}.",
                            hint="Tell the customer the available sizes.",
                            details={"available_sizes": sizes})

    selected = [v for v in variants
                if (colour is None or v["color"] == colour) and (size is None or v["size"] == size)]
    payload: dict = {
        "product_id": p["id"],
        "name": p["name"],
        "price_eur": p["price_eur"],
        "variants": [_variant_view(v) for v in selected],
    }
    if colour and size and all(v["stock"] <= 0 for v in selected):
        payload["alternatives"] = {
            "same_size_other_colors": [v["color"] for v in variants
                                       if v["size"] == size and v["stock"] > 0],
            "same_color_other_sizes": [v["size"] for v in variants
                                       if v["color"] == colour and v["stock"] > 0],
        }
    return payload


# --------------------------------------------------------------------------- size recommendation

class SizeRecommendationInput(ProductRef):
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
    p = _load_product(ctx, args.product_id)
    try:
        rec = recommend(
            garment_type=p["garment_type"],
            chart_gender=p["chart_gender"],
            size_order=p["size_order"],
            sizes=p["sizes"],
            product_fit=p["fit"],
            measurements=Measurements(args.height_cm, args.weight_kg, args.chest_cm,
                                      args.waist_cm, args.hip_cm, args.foot_length_cm),
            preference=args.fit_preference,
        )
    except MissingMeasurement as exc:
        raise ToolError("MISSING_MEASUREMENT", f"Need {exc} to recommend a size.",
                        hint="Ask the customer for it. For shoes ask for foot length in cm "
                             "(heel to longest toe).") from exc

    in_stock_colours = [v["color"] for v in p["variants"]
                        if v["size"] == rec.recommended_size and v["stock"] > 0]
    return {
        "product_id": p["id"],
        "name": p["name"],
        "product_fit": p["fit"],
        "recommended_size": rec.recommended_size,
        "alternative_size": rec.alternative_size,
        "confidence": rec.confidence,
        "basis": rec.basis,
        "measurements_used": rec.measurements_used,
        "notes": rec.notes,
        "recommended_size_in_stock_colors": in_stock_colours,
    }


# --------------------------------------------------------------------------- specs

SEARCH_PRODUCTS = ToolSpec(
    name="search_products",
    description=(
        "Search the Quilora catalog. Use it whenever the customer looks for products, asks "
        "what exists, or mentions a budget, colour or size. Returns up to `limit` products with "
        "price, material and the colours/sizes currently in stock. The catalog is in English: "
        "translate keywords and colours before calling. Use get_product or check_stock for "
        "details of one product."
    ),
    input_model=SearchProductsInput,
    handler=search_products,
)

GET_PRODUCT = ToolSpec(
    name="get_product",
    description=(
        "Get full details of one product by ID: description, material, fit, care instructions, "
        "final-sale flag, sizes and an availability matrix by colour and size. Use it when the "
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
        "Recommend a size for a specific product using its size chart and fit. Accepts height "
        "and weight (gives an estimate with low confidence) and/or chest, waist and hip "
        "measurements in cm (more reliable); shoes need foot length. Always use this tool "
        "instead of guessing a size. Explain the confidence and notes to the customer."
    ),
    input_model=SizeRecommendationInput,
    handler=get_size_recommendation,
)
