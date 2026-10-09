"""Size recommendation: deterministic code, not model reasoning.

The model only collects the customer's data and explains the result. Every number comes
from here, so it is testable and the same input always gives the same answer.

When the customer gives only height and weight, body measurements are *estimated* with
a deliberately simple linear heuristic around an average body for each chart's gender.
It is a rough guide: confidence is reported as "low" and the customer is invited to
measure. Replacing it with a model trained on real return data is a listed next step.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Preference = Literal["closer", "regular", "looser"]

# Which body measurements decide the size for each garment type.
RELEVANT_DIMENSIONS = {
    "top": ["chest", "waist"],
    "bottom": ["waist", "hip"],
    "dress": ["chest", "waist", "hip"],
    "shoes": ["foot_length"],
}


@dataclass(frozen=True)
class Measurements:
    """What the customer told us about their body; any field may be missing."""
    height_cm: float | None = None
    weight_kg: float | None = None
    chest_cm: float | None = None
    waist_cm: float | None = None
    hip_cm: float | None = None
    foot_length_cm: float | None = None

    def get(self, dim: str) -> float | None:
        """Return a measurement by dimension name ('chest', 'waist', ...)."""
        return getattr(self, f"{dim}_cm")


@dataclass
class SizeRecommendation:
    """Recommended size with alternative, confidence, basis and notes for the customer."""
    recommended_size: str
    alternative_size: str | None
    confidence: Literal["high", "medium", "low"]
    basis: Literal["measurements", "partial_measurements", "height_weight_estimate", "one_size"]
    measurements_used: dict[str, dict[str, float | bool]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class MissingMeasurement(ValueError):
    """Raised when there is not enough information to recommend a size."""


def estimate_body(height_cm: float, weight_kg: float, gender: str) -> dict[str, float]:
    """Rough chest/waist/hip estimate (cm) from height and weight. Heuristic, see module doc."""
    bmi = weight_kg / (height_cm / 100) ** 2
    if gender == "women":
        base_bmi, base_h = 21.5, 165.0
        chest = 86 + 1.9 * (bmi - base_bmi) + 0.15 * (height_cm - base_h)
        waist = 70 + 2.3 * (bmi - base_bmi) + 0.10 * (height_cm - base_h)
        hip = 96 + 2.1 * (bmi - base_bmi) + 0.25 * (height_cm - base_h)
    else:  # men and unisex charts
        base_bmi, base_h = 23.5, 178.0
        chest = 98 + 1.9 * (bmi - base_bmi) + 0.15 * (height_cm - base_h)
        waist = 86 + 2.6 * (bmi - base_bmi) + 0.10 * (height_cm - base_h)
        hip = 99 + 1.8 * (bmi - base_bmi) + 0.20 * (height_cm - base_h)
    return {"chest": round(chest, 1), "waist": round(waist, 1), "hip": round(hip, 1)}


def _locate(value: float, ranges: list[tuple[float, float]]) -> tuple[int, float, bool]:
    """Return (size index, position within that size 0..1, inside_chart)."""
    for i, (low, high) in enumerate(ranges):
        if low <= value < high:
            return i, (value - low) / (high - low), True
    if value < ranges[0][0]:
        return 0, 0.0, False
    return len(ranges) - 1, 1.0, False


def recommend(
    *,
    garment_type: str,
    chart_gender: str,
    size_order: list[str],
    sizes: dict[str, dict[str, list[float]]],
    product_fit: str,
    measurements: Measurements,
    preference: Preference = "regular",
) -> SizeRecommendation:
    """Pick a size from the product's size chart, adjusting for fit and the customer's preference.
    """
    if garment_type == "one_size":
        return SizeRecommendation(size_order[0], None, "high", "one_size",
                                  notes=["This item is one size."])

    dims = RELEVANT_DIMENSIONS[garment_type]
    used: dict[str, dict[str, float | bool]] = {}
    for dim in dims:
        value = measurements.get(dim)
        if value is not None:
            used[dim] = {"value_cm": value, "estimated": False}

    if garment_type == "shoes":
        if "foot_length" not in used:
            raise MissingMeasurement("foot_length_cm")
    else:
        missing = [d for d in dims if d not in used]
        if missing and measurements.height_cm and measurements.weight_kg:
            estimate = estimate_body(measurements.height_cm, measurements.weight_kg, chart_gender)
            for dim in missing:
                used[dim] = {"value_cm": estimate[dim], "estimated": True}
        if not used:
            raise MissingMeasurement("height_cm and weight_kg, or body measurements")

    notes: list[str] = []
    best_index, best_position = -1, 0.0
    for dim, info in used.items():
        ranges = [tuple(sizes[s][dim]) for s in size_order]
        index, position, inside = _locate(float(info["value_cm"]), ranges)
        if not inside:
            notes.append(f"Your {dim.replace('_', ' ')} is outside this product's size range.")
        # The garment must fit the dimension that needs the most room.
        if index > best_index or (index == best_index and position > best_position):
            best_index, best_position = index, position

    index = best_index
    if product_fit == "slim" and best_position >= 0.6:
        index += 1
        notes.append("Slim fit and you are at the top of the size range: one size up.")
    if preference == "looser" and best_position >= 0.5:
        index += 1
        notes.append("Sized up because you prefer a looser fit.")
    if preference == "closer" and best_position <= 0.4 and product_fit in {"relaxed", "oversized"}:
        index -= 1
        notes.append("Sized down because you prefer a closer fit and this item is cut loose.")
    index = max(0, min(index, len(size_order) - 1))

    alternative = None
    if best_position >= 0.7 and index + 1 < len(size_order):
        alternative = size_order[index + 1]
    elif best_position <= 0.3 and index - 1 >= 0:
        alternative = size_order[index - 1]
    if product_fit == "oversized" and preference == "regular":
        notes.append("Oversized fit: choose the smaller size if you want it closer to the body.")

    estimated = [d for d, info in used.items() if info["estimated"]]
    if not estimated:
        basis, confidence = "measurements", "high"
    elif len(estimated) < len(used):
        basis, confidence = "partial_measurements", "medium"
    else:
        basis, confidence = "height_weight_estimate", "low"
        notes.append("Estimated from height and weight only; measuring chest, waist and hips "
                     "gives a more reliable result.")
    if any("outside" in n for n in notes):
        confidence = "low"

    return SizeRecommendation(size_order[index], alternative, confidence, basis, used, notes)
