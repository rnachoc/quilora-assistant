"""search_policies: retrieve the store policy sections that answer a question."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from quilora.search import policies
from quilora.tools.base import ToolContext, ToolSpec


class SearchPoliciesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=2, max_length=200,
                       description="The customer's question, rephrased IN ENGLISH with the key "
                                   "terms, e.g. 'return window days', 'shipping cost Balearic "
                                   "Islands'.")
    limit: int = Field(default=3, ge=1, le=5, description="Number of sections to return.")


def search_policies(ctx: ToolContext, args: SearchPoliciesInput) -> dict:
    with ctx.db.connection() as conn:
        hits, backend = policies.search(
            conn, args.query, backend=ctx.settings.policy_search_backend,
            limit=args.limit, embedder=ctx.embedder,
        )
    results = [
        {"policy_id": h.chunk_id, "citation": h.citation, "text": h.content, "score": h.score}
        for h in hits
    ]
    payload: dict = {"backend": backend, "results": results}
    if results:
        payload["hint"] = ("Answer only from these sections. Cite the one you used, e.g. "
                           f"'({hits[0].doc_title} §{hits[0].section_no})'. If they do not answer "
                           "the question, say so and offer a transfer to the team.")
    else:
        payload["hint"] = ("No policy found. Do not guess: say you are not sure and offer a "
                           "transfer to the support team.")
    return payload


SEARCH_POLICIES = ToolSpec(
    name="search_policies",
    description=(
        "Search Quilora's official policies: shipping (costs, delivery times by region, "
        "tracking, delays), returns (window, conditions, non-returnable items, methods, "
        "refunds), exchanges, payments (methods, discount codes, invoices), garment care, "
        "sizing advice, customer support and FAQs. Call it before answering any policy "
        "question and cite the section you used. Returns the most relevant sections."
    ),
    input_model=SearchPoliciesInput,
    handler=search_policies,
)
