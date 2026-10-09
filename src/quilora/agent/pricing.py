"""Cost estimation from token usage.

IMPORTANT: prices change and were NOT verified against the official page when this file
was written (the docs were not reachable from the build environment). Before quoting any
cost figure, copy the current values from
https://platform.claude.com/docs/en/about-claude/pricing and set PRICING_VERIFIED = True.
Reports print a warning while it is False.

The cache multipliers (writes 1.25x base input, reads 0.1x base input, 5-minute TTL) are the
documented defaults for ephemeral prompt caching at the time of writing; verify them too.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

from dataclasses import dataclass

from quilora.agent.model import TokenUsage

PRICING_VERIFIED = False

CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


@dataclass(frozen=True)
class ModelPrice:
    """List prices of one model in USD per million tokens."""
    input_per_mtok: float
    output_per_mtok: float


# USD per million tokens. Placeholder values (previous-generation list prices for the same
# tiers); replace with the official figures.
PRICES: dict[str, ModelPrice] = {
    "claude-sonnet-5-5": ModelPrice(input_per_mtok=3.00, output_per_mtok=15.00),
    "claude-haiku-5-5": ModelPrice(input_per_mtok=1.00, output_per_mtok=5.00),
    "claude-opus-5-5": ModelPrice(input_per_mtok=5.00, output_per_mtok=25.00),
}


def estimate_cost_usd(model: str, usage: TokenUsage) -> float | None:
    """Return the estimated cost in USD, or None for an unknown model."""
    price = next((p for name, p in PRICES.items() if model.startswith(name)), None)
    if price is None:
        return None
    per_token_in = price.input_per_mtok / 1_000_000
    per_token_out = price.output_per_mtok / 1_000_000
    cost = (
        usage.input_tokens * per_token_in
        + usage.cache_creation_input_tokens * per_token_in * CACHE_WRITE_MULTIPLIER
        + usage.cache_read_input_tokens * per_token_in * CACHE_READ_MULTIPLIER
        + usage.output_tokens * per_token_out
    )
    return round(cost, 6)
