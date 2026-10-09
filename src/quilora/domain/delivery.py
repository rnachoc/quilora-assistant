"""Delivery estimates in business days. Pure functions: deterministic and fully tested.

"If I order today, when will it arrive?" is one of the most frequent questions in fashion
e-commerce, and dropshipping shops add long, variable transit times. The answer is
arithmetic on the store profile (processing days, cut-off hour, weekends, holidays, transit
days per zone), so it is computed here instead of being reasoned by the model.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta


def is_business_day(day: date, holidays: set[date]) -> bool:
    """Monday to Friday and not a holiday."""
    return day.weekday() < 5 and day not in holidays


def next_business_day(day: date, holidays: set[date]) -> date:
    """The given day if it is a business day, otherwise the next one."""
    while not is_business_day(day, holidays):
        day += timedelta(days=1)
    return day


def add_business_days(start: date, days: int, holidays: set[date]) -> date:
    """Move forward `days` business days from `start` (0 returns `start` itself)."""
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if is_business_day(current, holidays):
            remaining -= 1
    return current


@dataclass(frozen=True)
class DeliveryWindow:
    """When an order is expected to ship and to arrive."""

    processing_starts: date
    ships_between: tuple[date, date]
    arrives_between: tuple[date, date]

    def as_dict(self) -> dict:
        """JSON-friendly form for tool results."""
        return {
            "processing_starts": self.processing_starts.isoformat(),
            "ships_between": [d.isoformat() for d in self.ships_between],
            "arrives_between": [d.isoformat() for d in self.arrives_between],
        }


def estimate_window(
    *,
    ordered_at: datetime,
    processing_business_days: tuple[int, int],
    transit_business_days: tuple[int, int],
    holidays: set[date],
    cutoff_hour: int | None = None,
) -> DeliveryWindow:
    """Estimate shipping and delivery dates for an order placed at `ordered_at` (store time).

    Orders placed after the cut-off hour, at weekends or on holidays start processing on
    the next business day. Processing and transit are both counted in business days.
    """
    start = ordered_at.date()
    if cutoff_hour is not None and ordered_at.hour >= cutoff_hour:
        start += timedelta(days=1)
    start = next_business_day(start, holidays)

    proc_lo, proc_hi = processing_business_days
    transit_lo, transit_hi = transit_business_days
    ship_first = add_business_days(start, proc_lo, holidays)
    ship_last = add_business_days(start, proc_hi, holidays)
    return DeliveryWindow(
        processing_starts=start,
        ships_between=(ship_first, ship_last),
        arrives_between=(add_business_days(ship_first, transit_lo, holidays),
                         add_business_days(ship_last, transit_hi, holidays)),
    )
