"""Store profile: everything that makes the assistant belong to ONE particular shop.

The code is store-agnostic. Name, languages, contact details, shipping zones, return and
cancellation rules, tracking links and public promotions are read from a validated YAML
file (`STORE_DIR/store.yaml`). Tools compute answers from these structured facts; the
policy texts are what the assistant cites.

Why structured facts and not only policy text? Real shops' policies often contradict
themselves (for example "30 days" in one section and "14 days" in another). Numbers that
drive decisions (return window, processing days, delivery windows) must have one source
of truth, and `quilora.store.consistency` checks the policy text against it.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Members of the European Union (ISO 3166-1 alpha-2), used by the "EU" zone macro.
EU_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT",
    "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
}
# EU consumer law gives a 14-day right of withdrawal for distance sales.
EU_MIN_WITHDRAWAL_DAYS = 14

OrderStatus = Literal["processing", "shipped", "in_transit", "delivered", "cancelled", "returned"]


class _Model(BaseModel):
    """Profile sections: unknown keys are errors (typos never pass silently), values are
    immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Contact(_Model):
    """How customers reach the human support team."""

    email: str | None = None
    phone: str | None = None
    channels: list[str] = Field(default_factory=list)
    hours: str
    # Promise shown after a handoff, e.g. "within 24 business hours".
    response_time: str


class ShippingZone(_Model):
    """A delivery area with its transit time and price."""

    id: str
    name: str
    # ISO 3166-1 alpha-2 codes, subdivisions such as "ES-CN", the macro "EU", or "*" (rest).
    destinations: list[str]
    transit_business_days: tuple[int, int]
    cost: float = 0.0
    free_from: float | None = None
    notes: str | None = None
    policy_ref: str | None = None  # policy section to cite, e.g. "SHP-2"

    @model_validator(mode="after")
    def _ordered(self):
        """Transit days must be a [min, max] range."""
        lo, hi = self.transit_business_days
        if not 0 <= lo <= hi:
            raise ValueError(f"zone {self.id}: transit_business_days must be [min, max]")
        return self


class Shipping(_Model):
    """How long orders take to leave the warehouse and where they can go."""

    processing_business_days: tuple[int, int]
    cutoff_hour: int | None = Field(default=None, ge=0, le=23,
                                    description="Orders after this local hour start next day.")
    holidays: list[date] = Field(default_factory=list)
    ships_from: str | None = None
    split_shipments_possible: bool = False
    zones: list[ShippingZone]
    policy_ref: str | None = None


class Returns(_Model):
    """How returns work in this shop."""

    window_days: int = Field(ge=0)
    window_starts: Literal["delivery"] = "delivery"
    return_shipping_paid_by: Literal["store", "customer", "depends_on_method"]
    method: Literal["prepaid_label", "address_on_request", "drop_off_point"]
    method_details: str
    exchanges_allowed: bool
    refund_days: int = Field(ge=0, description="Days to refund after receiving the return.")
    non_returnable: list[str] = Field(default_factory=list)
    defective_items_to_support: bool = True
    policy_refs: dict[str, str] = Field(default_factory=dict)


class OrderChanges(_Model):
    """Which order statuses still allow a cancellation or address change request."""

    cancellation_allowed_statuses: list[OrderStatus] = Field(default_factory=list)
    address_change_allowed_statuses: list[OrderStatus] = Field(default_factory=list)
    policy_ref: str | None = None


class Promotion(_Model):
    """A PUBLIC promotion the assistant may share. Codes not listed here are never given."""

    code: str | None = None
    description: str
    conditions: str | None = None
    valid_from: date | None = None
    valid_until: date | None = None

    def active_on(self, day: date) -> bool:
        """True if the promotion is valid on the given day."""
        return (self.valid_from is None or self.valid_from <= day) and (
            self.valid_until is None or day <= self.valid_until)


class Catalog(_Model):
    """How the catalog is written and searched."""

    language: str = Field(description="Language of product and policy texts, e.g. 'en', 'es'.")
    # PostgreSQL text-search configuration matching that language ('english', 'spanish', ...).
    search_config: str = "english"
    # Store-wide size charts used when a product has none (by department).
    fallback_size_charts: dict[Literal["women", "men", "unisex"], str] = Field(
        default_factory=dict)


class StoreProfile(_Model):
    """The full description of one shop. See data/store.yaml for a documented example."""

    id: str
    name: str
    description: str
    website: str | None = None
    timezone: str = "Europe/Madrid"
    currency: str = "EUR"
    languages: list[str] = Field(min_length=1)
    eu_consumer_law: bool = True
    catalog: Catalog
    contact: Contact
    shipping: Shipping
    returns: Returns
    order_changes: OrderChanges = Field(default_factory=OrderChanges)
    tracking_url_template: str | None = Field(
        default=None, description="Customer tracking page, with {tracking_code} placeholder.")
    promotions: list[Promotion] = Field(default_factory=list)

    @field_validator("tracking_url_template")
    @classmethod
    def _placeholder(cls, value: str | None) -> str | None:
        """The template must contain {tracking_code}."""
        if value and "{tracking_code}" not in value:
            raise ValueError("tracking_url_template must contain {tracking_code}")
        return value

    def warnings(self) -> list[str]:
        """Business or legal inconsistencies worth a human look (not fatal)."""
        found = []
        if self.eu_consumer_law and self.returns.window_days < EU_MIN_WITHDRAWAL_DAYS:
            found.append(f"Return window ({self.returns.window_days} days) is shorter than the "
                         f"EU {EU_MIN_WITHDRAWAL_DAYS}-day withdrawal period.")
        if self.eu_consumer_law and not self.order_changes.cancellation_allowed_statuses:
            found.append("Orders can never be cancelled; EU consumers can still withdraw after "
                         "delivery. Make sure the policy explains that route.")
        return found

    def zone_for(self, destination: str) -> ShippingZone | None:
        """Most specific zone for a destination: 'ES-CN', then 'ES', then 'EU', then '*'."""
        code = destination.strip().upper()
        country = code.split("-")[0]
        for candidate in (code, country):
            for zone in self.shipping.zones:
                if candidate in zone.destinations:
                    return zone
        if country in EU_COUNTRIES:
            for zone in self.shipping.zones:
                if "EU" in zone.destinations:
                    return zone
        for zone in self.shipping.zones:
            if "*" in zone.destinations:
                return zone
        return None

    def active_promotions(self, day: date) -> list[Promotion]:
        """Public promotions valid on the given day."""
        return [p for p in self.promotions if p.active_on(day)]


@lru_cache(maxsize=8)
def load_profile(store_dir: str) -> StoreProfile:
    """Load and validate STORE_DIR/store.yaml (cached per directory)."""
    path = Path(store_dir) / "store.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Store profile not found: {path}")
    return StoreProfile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
