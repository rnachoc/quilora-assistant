"""Return eligibility rules (see data/policies/returns.md). Pure functions, fully tested.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

RETURN_WINDOW_DAYS = 30  # Returns Policy §1


@dataclass(frozen=True)
class Eligibility:
    """Whether an order line can be returned, why, how many units and until when."""
    eligible: bool
    # eligible | not_delivered | cancelled | final_sale | window_expired | already_returned
    reason: str
    returnable_quantity: int
    deadline: date | None

    def as_dict(self) -> dict:
        """JSON-friendly form included in tool results."""
        return {
            "eligible": self.eligible,
            "reason": self.reason,
            "returnable_quantity": self.returnable_quantity,
            "return_deadline": self.deadline.isoformat() if self.deadline else None,
        }


def item_eligibility(
    *,
    order_status: str,
    delivered_on: date | None,
    today: date,
    final_sale: bool,
    quantity: int,
    already_returned: int,
) -> Eligibility:
    """Apply the Returns Policy rules (status, final sale, 30-day window, prior returns) to one
    line.
    """
    deadline = delivered_on + timedelta(days=RETURN_WINDOW_DAYS) if delivered_on else None
    remaining = max(0, quantity - already_returned)

    if order_status == "cancelled":
        return Eligibility(False, "cancelled", 0, None)
    if order_status in {"processing", "shipped", "in_transit"} or delivered_on is None:
        return Eligibility(False, "not_delivered", 0, None)
    if final_sale:
        return Eligibility(False, "final_sale", 0, deadline)
    if remaining == 0:
        return Eligibility(False, "already_returned", 0, deadline)
    if today > deadline:
        return Eligibility(False, "window_expired", 0, deadline)
    return Eligibility(True, "eligible", remaining, deadline)
