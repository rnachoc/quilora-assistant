"""Phase 3: pure business rules (sizing and return eligibility).

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

from datetime import date

import pytest

from quilora.domain.returns import item_eligibility
from quilora.domain.sizing import Measurements, MissingMeasurement, estimate_body, recommend

WOMEN_BOTTOMS = {
    "XS": {"waist": [60, 64], "hip": [86, 90]},
    "S": {"waist": [64, 68], "hip": [90, 94]},
    "M": {"waist": [68, 72], "hip": [94, 98]},
    "L": {"waist": [72, 78], "hip": [98, 104]},
    "XL": {"waist": [78, 84], "hip": [104, 110]},
}
ORDER = ["XS", "S", "M", "L", "XL"]


def _rec(m: Measurements, fit="regular", pref="regular"):
    return recommend(garment_type="bottom", chart_gender="women", size_order=ORDER,
                     sizes=WOMEN_BOTTOMS, product_fit=fit, measurements=m, preference=pref)


def test_height_and_weight_from_the_brief_gives_m_with_low_confidence():
    rec = _rec(Measurements(height_cm=168, weight_kg=60))
    assert rec.recommended_size == "M"
    assert rec.confidence == "low"
    assert rec.basis == "height_weight_estimate"


def test_real_measurements_give_high_confidence_and_largest_dimension_wins():
    # waist says S, hip says M -> the garment must fit the hips
    rec = _rec(Measurements(waist_cm=66, hip_cm=95))
    assert rec.recommended_size == "M"
    assert rec.confidence == "high"


def test_slim_fit_at_top_of_range_sizes_up():
    rec = _rec(Measurements(waist_cm=71, hip_cm=97.5), fit="slim")
    assert rec.recommended_size == "L"


def test_looser_preference_sizes_up_from_upper_half():
    assert _rec(Measurements(waist_cm=70.5, hip_cm=96.5), pref="looser").recommended_size == "L"


def test_outside_chart_is_flagged_low_confidence():
    rec = _rec(Measurements(waist_cm=95, hip_cm=120))
    assert rec.recommended_size == "XL"
    assert rec.confidence == "low"
    assert any("outside" in n for n in rec.notes)


def test_partial_measurements_fill_the_rest_from_estimate():
    rec = _rec(Measurements(height_cm=168, weight_kg=60, waist_cm=69))
    assert rec.basis == "partial_measurements"
    assert rec.confidence == "medium"


def test_missing_data_raises():
    with pytest.raises(MissingMeasurement):
        _rec(Measurements())


def test_shoes_need_foot_length():
    sizes = {"38": {"foot_length": [23.9, 24.6]}, "39": {"foot_length": [24.6, 25.3]}}
    with pytest.raises(MissingMeasurement):
        recommend(garment_type="shoes", chart_gender="women", size_order=["38", "39"],
                  sizes=sizes, product_fit="regular",
                  measurements=Measurements(height_cm=168, weight_kg=60))
    rec = recommend(garment_type="shoes", chart_gender="women", size_order=["38", "39"],
                    sizes=sizes, product_fit="regular",
                    measurements=Measurements(foot_length_cm=24.7))
    assert rec.recommended_size == "39"


def test_estimate_is_monotonic_in_weight():
    light = estimate_body(170, 55, "women")
    heavy = estimate_body(170, 75, "women")
    assert all(heavy[k] > light[k] for k in light)


# --- return eligibility -----------------------------------------------------------------

TODAY = date(2026, 10, 1)


def _elig(**overrides):
    base = dict(order_status="delivered", delivered_on=date(2026, 9, 20), today=TODAY,
                final_sale=False, quantity=1, already_returned=0)
    base.update(overrides)
    return item_eligibility(**base)


def test_eligible_within_window_with_deadline():
    e = _elig()
    assert e.eligible and e.deadline == date(2026, 10, 20)


def test_last_day_is_still_eligible_and_next_day_is_not():
    assert _elig(today=date(2026, 10, 20)).eligible
    assert _elig(today=date(2026, 10, 21)).reason == "window_expired"


@pytest.mark.parametrize("overrides, reason", [
    ({"order_status": "in_transit", "delivered_on": None}, "not_delivered"),
    ({"order_status": "cancelled"}, "cancelled"),
    ({"final_sale": True}, "final_sale"),
    ({"quantity": 2, "already_returned": 2}, "already_returned"),
])
def test_not_eligible_reasons(overrides, reason):
    e = _elig(**overrides)
    assert not e.eligible and e.reason == reason


def test_partial_previous_return_leaves_remaining_quantity():
    assert _elig(quantity=2, already_returned=1).returnable_quantity == 1
