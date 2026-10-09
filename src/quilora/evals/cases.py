"""Evaluation case schema. Cases live in evals/cases/*.yaml and are validated on load.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from quilora.paths import EVALS_DIR

CASES_DIR = EVALS_DIR / "cases"

Category = Literal["product_search", "sizing", "stock", "order_status", "returns", "policies",
                   "off_topic", "ambiguous", "attacks", "handoff", "multi_turn"]


class Expect(BaseModel):
    """All fields are optional; each one present becomes one check.

    Tool checks look at the turns the expectation applies to (one turn, or the whole
    conversation for the final `expect`). Reply checks look at the last reply.
    Text matching is case- and accent-insensitive.
    """

    model_config = ConfigDict(extra="forbid")

    tools_called: list[str] = Field(default_factory=list)
    tools_not_called: list[str] = Field(default_factory=list)
    no_tools: bool | None = None
    # {"search_products": {"max_price_eur": {"lte": 60}, "color": {"contains": "black"}}}
    tool_args: dict[str, dict[str, Any]] = Field(default_factory=dict)
    error_codes_include: list[str] = Field(default_factory=list)
    reply_contains_all: list[str] = Field(default_factory=list)
    reply_contains_any: list[str] = Field(default_factory=list)
    reply_not_contains: list[str] = Field(default_factory=list)
    reply_matches: list[str] = Field(default_factory=list)  # regexes, all must match
    language: Literal["es", "en"] | None = None
    handoff: bool | None = None
    return_created: bool | None = None
    flags_include: list[str] = Field(default_factory=list)
    flags_exclude: list[str] = Field(default_factory=list)


class Turn(BaseModel):
    """One customer message in a case, optionally with checks for that turn only."""
    model_config = ConfigDict(extra="forbid")
    user: str
    expect: Expect | None = None


class Case(BaseModel):
    """One evaluation scenario: customer turns plus the expected behaviour."""
    model_config = ConfigDict(extra="forbid")

    id: str
    category: Category
    description: str
    turns: list[Turn]
    expect: Expect = Field(default_factory=Expect)
    # Optional rubric for the LLM judge (only used with --judge).
    judge: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _plain_string_turns(cls, data: Any) -> Any:
        """Allow turns to be written as plain strings in YAML."""
        if isinstance(data, dict) and isinstance(data.get("turns"), list):
            data["turns"] = [{"user": t} if isinstance(t, str) else t for t in data["turns"]]
        return data


def load_cases(directory: Path = CASES_DIR) -> list[Case]:
    """Load and validate every YAML case file, rejecting duplicate IDs."""
    cases: list[Case] = []
    for file in sorted(directory.glob("*.yaml")):
        for raw in yaml.safe_load(file.read_text(encoding="utf-8")) or []:
            cases.append(Case.model_validate(raw))
    ids = [c.id for c in cases]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"Duplicate case ids: {sorted(duplicates)}")
    return cases
