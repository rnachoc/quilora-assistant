"""Store-level tools: estimate_delivery and get_active_promotions.

Both answer from the store profile (structured facts), so answers are exact and identical
for every customer, instead of being re-derived by the model from policy prose.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from quilora.domain.delivery import estimate_window
from quilora.tools.base import ToolContext, ToolError, ToolSpec

DESTINATION_PATTERN = re.compile(r"^[A-Z]{2}(-[A-Z0-9]{1,3})?$")


def policy_citation(ctx: ToolContext, ref: str | None) -> str | None:
    """Turn a policy section ID ('SHP-2') into a citation ('Shipping Policy §2 (...)')."""
    if not ref:
        return None
    with ctx.db.connection() as conn:
        row = conn.execute("SELECT doc_title, section_no, section_title FROM policy_chunks"
                           " WHERE id = %s", (ref,)).fetchone()
    return f"{row['doc_title']} §{row['section_no']} ({row['section_title']})" if row else None


class EstimateDeliveryInput(BaseModel):
    """Input of estimate_delivery: where the order goes and, optionally, its value."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    destination: str = Field(
        description="ISO 3166-1 alpha-2 country code, or a region code when the region has "
                    "its own shipping terms: ES-IB Balearic Islands, ES-CN Canary Islands, "
                    "ES-CE Ceuta, ES-ML Melilla. Map city or island names yourself "
                    "(Sevilla -> ES, Mallorca -> ES-IB, Tenerife -> ES-CN, Lisboa -> PT).")
    order_subtotal_eur: float | None = Field(
        default=None, ge=0, description="Basket value, to tell whether shipping is free.")

    @field_validator("destination")
    @classmethod
    def _code(cls, value: str) -> str:
        """Upper-case and require a country or region code."""
        value = value.upper()
        if not DESTINATION_PATTERN.match(value):
            raise ValueError("use a code like 'ES', 'PT' or 'ES-CN'")
        return value


def estimate_delivery(ctx: ToolContext, args: EstimateDeliveryInput) -> dict:
    """Handler: delivery window and shipping cost for an order placed now."""
    store = ctx.settings.store
    zone = store.zone_for(args.destination)
    if zone is None:
        raise ToolError(
            "NO_SHIPPING", f"{store.name} does not ship to {args.destination}.",
            hint="Tell the customer and list where the shop ships.",
            details={"zones": [z.name for z in store.shipping.zones]})
    window = estimate_window(
        ordered_at=ctx.settings.now(),
        processing_business_days=store.shipping.processing_business_days,
        transit_business_days=zone.transit_business_days,
        holidays=set(store.shipping.holidays),
        cutoff_hour=store.shipping.cutoff_hour,
    )
    shipping = {"standard_cost_eur": zone.cost, "free_from_eur": zone.free_from}
    if args.order_subtotal_eur is not None:
        free = zone.cost == 0 or (zone.free_from is not None
                                  and args.order_subtotal_eur >= zone.free_from)
        shipping["cost_for_this_order_eur"] = 0.0 if free else zone.cost
    payload = {
        "destination": args.destination,
        "zone": zone.name,
        "if_ordered_now": window.as_dict(),
        "processing_business_days": list(store.shipping.processing_business_days),
        "transit_business_days": list(zone.transit_business_days),
        "shipping": shipping,
        "notes": [n for n in [
            zone.notes,
            "Business days exclude weekends and public holidays; peaks can add delays.",
            "Items may arrive in separate parcels." if store.shipping.split_shipments_possible
            else None,
        ] if n],
        "citation": policy_citation(ctx, zone.policy_ref),
    }
    if store.shipping.cutoff_hour is not None:
        payload["cutoff"] = (f"Orders after {store.shipping.cutoff_hour}:00 "
                             f"({store.timezone}) start processing the next business day.")
    return payload


class NoInput(BaseModel):
    """Tools without parameters."""

    model_config = ConfigDict(extra="forbid")


def get_active_promotions(ctx: ToolContext, _args: NoInput) -> dict:
    """Handler: public promotions valid today, straight from the store profile."""
    store = ctx.settings.store
    today = ctx.settings.today()
    promotions = [p.model_dump(mode="json", exclude_none=True)
                  for p in store.active_promotions(today)]
    payload: dict = {"date": today.isoformat(), "promotions": promotions}
    payload["hint"] = (
        "Share only these promotions, exactly as written, including conditions."
        if promotions else
        "There are no public promotions. Do not invent, promise or apply any discount; "
        "if relevant, say where the shop announces promotions according to its policies.")
    return payload


ESTIMATE_DELIVERY = ToolSpec(
    name="estimate_delivery",
    description=(
        "Estimate when an order placed now would ship and arrive at a destination, and what "
        "shipping costs there (free-shipping threshold included). Uses the shop's processing "
        "days, cut-off hour, holidays and transit days per zone. Use it for 'when will it "
        "arrive?', 'how much is shipping to...?' and 'do you ship to...?'. For an existing "
        "order use get_order_status instead."
    ),
    input_model=EstimateDeliveryInput,
    handler=estimate_delivery,
)

GET_ACTIVE_PROMOTIONS = ToolSpec(
    name="get_active_promotions",
    description=(
        "List the public promotions and discount codes {store_name} is running today. Call it "
        "whenever the customer asks about discounts, offers, coupons or codes. Only codes "
        "returned here may ever be shared."
    ),
    input_model=NoInput,
    handler=get_active_promotions,
)
