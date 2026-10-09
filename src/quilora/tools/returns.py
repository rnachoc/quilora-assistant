"""create_return_request: the only tool that changes business data.

It works in two phases, and every guarantee is enforced by code:

1. PROPOSE (no confirmation_token): checks the order was verified in THIS conversation,
   that every item belongs to it and is still returnable, then stores a pending proposal
   in the session and returns a summary plus a single-use confirmation token. Nothing is
   written to the database.

2. CONFIRM (with confirmation_token): only accepted if
     - the token exists in this session and has not expired,
     - it is redeemed in a LATER turn than the one that issued it, i.e. the customer has
       sent a new message after seeing the summary (the model cannot confirm on its own
       within the same turn),
     - the items and reason are exactly the ones proposed.
   Then the return and an audit entry are written in one transaction.

Idempotency has two layers: a confirmed token remembers its return ID (a replayed call
returns the same ID), and a unique idempotency key in the database stops two concurrent
confirmations from creating two returns.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from quilora.tools.base import ToolContext, ToolError, ToolSpec
from quilora.tools.orders import load_verified_order, order_view

CONFIRMATION_TTL = timedelta(minutes=30)
HANDOFF_REASONS = {"defective_or_damaged", "wrong_item"}


class ReturnItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_no: int = Field(ge=1, description="line_no of the item, from get_order_status.")
    quantity: int = Field(default=1, ge=1, le=20)


class CreateReturnInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    order_id: int = Field(ge=1, description="Order number already verified in this conversation.")
    items: list[ReturnItem] = Field(min_length=1, max_length=20)
    reason: Literal["doesnt_fit", "not_as_expected", "changed_mind", "defective_or_damaged",
                    "wrong_item", "other"]
    reason_details: str | None = Field(default=None, max_length=500,
                                       description="Optional short note from the customer.")
    confirmation_token: str | None = Field(
        default=None, max_length=50,
        description="Leave empty on the first call. Only pass the token from the summary "
                    "after the customer has explicitly confirmed in a new message.")

    @field_validator("items")
    @classmethod
    def _unique_lines(cls, items: list[ReturnItem]) -> list[ReturnItem]:
        lines = [i.line_no for i in items]
        if len(lines) != len(set(lines)):
            raise ValueError("each line_no may appear only once")
        return items


def _now() -> datetime:
    return datetime.now(UTC)


def _idempotency_key(order_id: int, items: list[ReturnItem], already_returned: dict) -> str:
    material = {
        "order_id": order_id,
        "items": sorted((i.line_no, i.quantity) for i in items),
        "returned_before": sorted(already_returned.items()),
    }
    return hashlib.sha256(json.dumps(material).encode()).hexdigest()


def _validated_items(ctx: ToolContext, args: CreateReturnInput) -> tuple[dict, list[dict]]:
    email = ctx.state.verified_orders.get(str(args.order_id))
    if email is None:
        raise ToolError(
            "ORDER_NOT_VERIFIED",
            f"Order {args.order_id} has not been verified in this conversation.",
            hint="Ask for the order number and purchase email, call get_order_status, then try "
                 "again.",
        )
    order = load_verified_order(ctx, args.order_id, email)
    view = order_view(order, ctx.settings.today())
    lines = {item["line_no"]: item for item in view["items"]}

    selected = []
    for wanted in args.items:
        item = lines.get(wanted.line_no)
        if item is None:
            raise ToolError("ITEM_NOT_IN_ORDER",
                            f"Order {args.order_id} has no line {wanted.line_no}.",
                            hint="Use the line_no values returned by get_order_status.",
                            details={"valid_lines": sorted(lines)})
        eligibility = item["return"]
        if not eligibility["eligible"]:
            raise ToolError(
                "ITEM_NOT_RETURNABLE",
                f"{item['product_name']} cannot be returned: {eligibility['reason']}.",
                hint="Explain why using the returns policy (search_policies) and offer a transfer "
                     "to the team if the customer disagrees.",
                details={"line_no": wanted.line_no, **eligibility},
            )
        if wanted.quantity > eligibility["returnable_quantity"]:
            raise ToolError("QUANTITY_TOO_HIGH",
                            f"Only {eligibility['returnable_quantity']} unit(s) of "
                            f"{item['product_name']} can be returned.",
                            hint="Ask the customer how many units they want to return.")
        selected.append({**item, "return_quantity": wanted.quantity})
    return order, selected


def _summary(order_id: int, selected: list[dict], args: CreateReturnInput) -> dict:
    return {
        "order_id": order_id,
        "items": [
            {"line_no": i["line_no"], "product_name": i["product_name"], "color": i["color"],
             "size": i["size"], "quantity": i["return_quantity"],
             "unit_price_eur": i["unit_price_eur"],
             "return_deadline": i["return"]["return_deadline"]}
            for i in selected
        ],
        "reason": args.reason,
        "what_happens_next": "A return reference and a prepaid label are sent by email "
                             "(Returns Policy §4). Drop-off is free in mainland Spain and the "
                             "Balearic Islands; home pickup costs 4.95 EUR (Returns Policy §5).",
    }


def create_return_request(ctx: ToolContext, args: CreateReturnInput) -> dict:
    # Replay of an already confirmed token (e.g. the model repeats the call): same answer,
    # no new side effect. Checked first, because the item is no longer returnable now.
    replay = ctx.state.pending_returns.get(args.confirmation_token or "")
    if replay and replay.get("return_id"):
        return {"status": "already_requested", "return_id": replay["return_id"],
                "note": "This exact return was already created; nothing new was done."}

    if args.reason in HANDOFF_REASONS:
        raise ToolError(
            "USE_HANDOFF",
            "Defective, damaged or wrong items are reviewed by the support team first "
            "(Returns Policy §7).",
            hint="Call handoff_to_human with reason 'defective_or_wrong_item' and a summary.",
        )

    order, selected = _validated_items(ctx, args)
    key = _idempotency_key(args.order_id, args.items, order["returned"])

    with ctx.db.connection() as conn:
        existing = conn.execute("SELECT id, created_at FROM return_requests"
                                " WHERE idempotency_key = %s", (key,)).fetchone()
    if existing:
        return {"status": "already_requested", "return_id": existing["id"],
                "note": "This exact return was already created; nothing new was done."}

    if not args.confirmation_token:
        # Phase 1: propose. Replace any older proposal for the same order.
        for token, pending in list(ctx.state.pending_returns.items()):
            if pending["order_id"] == args.order_id and not pending.get("return_id"):
                del ctx.state.pending_returns[token]
        token = secrets.token_urlsafe(6)
        ctx.state.pending_returns[token] = {
            "order_id": args.order_id,
            "key": key,
            "reason": args.reason,
            "issued_turn": ctx.turn_index,
            "expires_at": (_now() + CONFIRMATION_TTL).isoformat(),
        }
        return {
            "status": "confirmation_required",
            "confirmation_token": token,
            "summary": _summary(args.order_id, selected, args),
            "instructions": "Show this summary to the customer and ask for an explicit yes. "
                            "Only after they confirm in their next message, call this tool again "
                            "with the same order, items and reason plus this confirmation_token.",
        }

    # Phase 2: confirm.
    pending = ctx.state.pending_returns.get(args.confirmation_token)
    if pending is None or pending["order_id"] != args.order_id:
        raise ToolError("CONFIRMATION_INVALID", "That confirmation token is not valid here.",
                        hint="Call the tool without a token to get a fresh summary.")
    if datetime.fromisoformat(pending["expires_at"]) < _now():
        del ctx.state.pending_returns[args.confirmation_token]
        raise ToolError("CONFIRMATION_EXPIRED", "The confirmation expired.",
                        hint="Call the tool without a token to get a fresh summary.")
    if ctx.turn_index <= pending["issued_turn"]:
        raise ToolError(
            "CONFIRMATION_NEEDS_CUSTOMER_REPLY",
            "The customer has not replied since the summary was created.",
            hint="Show the summary and wait for the customer's explicit confirmation. You "
                 "cannot confirm on the customer's behalf.",
        )
    if pending["key"] != key or pending["reason"] != args.reason:
        raise ToolError("CONFIRMATION_MISMATCH",
                        "Items or reason differ from the summary the customer saw.",
                        hint="Call the tool without a token to create a new summary and ask the "
                             "customer to confirm it.")

    return_id = f"RR-{secrets.token_hex(4).upper()}"
    items_json = json.dumps([{"line_no": i.line_no, "quantity": i.quantity} for i in args.items])
    with ctx.db.connection() as conn:  # one transaction: return + audit entry
        row = conn.execute(
            "INSERT INTO return_requests (id, order_id, idempotency_key, items, reason,"
            " reason_details, session_id) VALUES (%s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (idempotency_key) DO NOTHING RETURNING id",
            (return_id, args.order_id, key, items_json, args.reason, args.reason_details,
             ctx.session_id),
        ).fetchone()
        if row is None:  # a concurrent request won the race: return its ID
            row = conn.execute("SELECT id FROM return_requests WHERE idempotency_key = %s",
                               (key,)).fetchone()
            return {"status": "already_requested", "return_id": row["id"]}
        conn.execute(
            "INSERT INTO audit_log (session_id, action, entity_id, payload)"
            " VALUES (%s, 'return_request.created', %s, %s)",
            (ctx.session_id, return_id,
             json.dumps({"order_id": args.order_id, "items": json.loads(items_json),
                         "reason": args.reason, "turn": ctx.turn_index})),
        )
    pending["return_id"] = return_id  # remembered so a replayed confirmation is idempotent
    return {
        "status": "created",
        "return_id": return_id,
        "summary": _summary(args.order_id, selected, args),
        "refund_policy": "The refund is issued to the original payment method within 14 days "
                         "after the warehouse receives and inspects the items (Returns Policy "
                         "§6). Do not promise a specific date.",
    }


CREATE_RETURN_REQUEST = ToolSpec(
    name="create_return_request",
    description=(
        "Start a return for items of an order that was verified with get_order_status in this "
        "conversation. Two steps: (1) call WITHOUT confirmation_token to validate the items "
        "and get a summary and a token; show the summary and ask the customer to confirm; "
        "(2) only after the customer explicitly says yes in a new message, call again with the "
        "same order, items and reason plus the token. Never pass a token the customer has not "
        "confirmed. Defective, damaged or wrong items are not handled here: use "
        "handoff_to_human."
    ),
    input_model=CreateReturnInput,
    handler=create_return_request,
    mutates=True,
)
