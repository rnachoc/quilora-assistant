"""handoff_to_human: open (or update) a support ticket with a summary of the case.

It only creates a ticket; it changes no order, payment or return. One open ticket per
conversation: calling it again updates the same ticket, so it is idempotent.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import json
import secrets
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from quilora.tools.base import ToolContext, ToolSpec
from quilora.tools.orders import EMAIL_PATTERN

Reason = Literal["complaint", "refund_or_payment_dispute", "defective_or_wrong_item",
                 "delivery_problem", "order_change_request", "customer_requested_human",
                 "verification_failed", "other"]

# Money disputes and complaints are always prioritised, whatever the model chose.
ALWAYS_HIGH = {"refund_or_payment_dispute", "complaint"}


class HandoffInput(BaseModel):
    """Input of handoff_to_human: reason, summary for the agent and optional contact data."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: Reason
    summary: str = Field(
        min_length=30, max_length=1500,
        description="Written for the support agent, in English: what the customer wants, "
                    "order number if any, what was already checked and what is pending. The "
                    "agent must be able to continue without asking the customer again.")
    priority: Literal["normal", "high"] = "normal"
    order_id: int | None = Field(default=None, ge=1)
    customer_email: str | None = Field(default=None, max_length=254,
                                       description="Only if the customer already gave it.")
    customer_language: Literal["es", "en", "other"] = "es"

    @field_validator("customer_email")
    @classmethod
    def _valid_email(cls, value: str | None) -> str | None:
        """Validate and lower-case the email if one was given."""
        if value is not None and not EMAIL_PATTERN.match(value):
            raise ValueError("not a valid email address")
        return value.lower() if value else value


def handoff_to_human(ctx: ToolContext, args: HandoffInput) -> dict:
    """Handler: open or update this conversation's ticket and audit it."""
    priority = "high" if args.reason in ALWAYS_HIGH else args.priority
    verified = args.order_id is not None and str(args.order_id) in ctx.state.verified_orders
    order_id = args.order_id
    with ctx.db.connection() as conn:
        if order_id is not None and not conn.execute(
            "SELECT 1 FROM orders WHERE id = %s", (order_id,)
        ).fetchone():
            # Keep the number in the summary, but do not link a non-existent order.
            order_id = None
        ticket_id = f"HT-{secrets.token_hex(4).upper()}"
        row = conn.execute(
            "INSERT INTO support_tickets (id, session_id, reason, priority, summary, order_id,"
            " order_verified, customer_email, language) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (session_id) WHERE status = 'open' DO UPDATE SET"
            "   summary = support_tickets.summary || E'\\n---\\n' || EXCLUDED.summary,"
            "   priority = CASE WHEN EXCLUDED.priority = 'high' THEN 'high'"
            "                   ELSE support_tickets.priority END,"
            "   order_id = COALESCE(EXCLUDED.order_id, support_tickets.order_id),"
            "   updated_at = now()"
            " RETURNING id, (xmax = 0) AS created",
            (ticket_id, ctx.session_id, args.reason, priority, args.summary, order_id, verified,
             args.customer_email, args.customer_language),
        ).fetchone()
        conn.execute(
            "INSERT INTO audit_log (session_id, action, entity_id, payload)"
            " VALUES (%s, %s, %s, %s)",
            (ctx.session_id,
             "support_ticket.created" if row["created"] else "support_ticket.updated",
             row["id"], json.dumps({"reason": args.reason, "priority": priority,
                                    "order_id": order_id})),
        )
    ctx.state.handoff_ticket_id = row["id"]
    return {
        "ticket_id": row["id"],
        "status": "created" if row["created"] else "updated",
        "priority": priority,
        "expected_response": "Within 24 business hours; the team works Monday to Friday, "
                             "9:00-18:00 Spanish peninsula time (Customer Support §1).",
        "instructions": "Give the customer the ticket ID and the expected response time. Do "
                        "not promise any outcome.",
    }


HANDOFF_TO_HUMAN = ToolSpec(
    name="handoff_to_human",
    description=(
        "Transfer the case to Quilora's support team by opening a ticket. Use it for complaints, "
        "refund or payment disputes, defective, damaged or wrong items, lost or delayed parcels, "
        "requests only the team can handle (address change, cancellation, exchange, invoice "
        "with company details), when the customer asks for a person, after failed order "
        "verification, or whenever you are unsure. Write a complete summary so nobody has to "
        "ask the customer again."
    ),
    input_model=HandoffInput,
    handler=handoff_to_human,
)
