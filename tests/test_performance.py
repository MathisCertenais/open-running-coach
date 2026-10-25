"""Tests for critical speed and durability (fade)."""

from __future__ import annotations

import pytest

from app.analysis import critical_speed, fade_index
from tests.builders import make_points, speed_for_pace


def performance(distance_m, time_s):
    return {"distance_m": distance_m, "time_s": time_s}


def test_critical_speed_fits_an_exact_line():
    # 1500 m in 5:00 and 4500 m in 20:00 sit on one line:
    # slope = 3000/900 = 3.333 m/s, intercept = 1500 - 3.333*300 = 500 m.
    fit = critical_speed([performance(1500, 300), performance(4500, 1200)])

    assert fit["speed_ms"] == pytest.approx(3.333, abs=0.01)
    assert fit["d_prime_m"] == pytest.approx(500, abs=5)
    assert fit["r2"] == pytest.approx(1.0, abs=1e-6)
    assert fit["points"] == 2


def test_critical_speed_converts_to_a_pace():
    fit = critical_speed([performance(1500, 300), performance(4500, 1200)])

    assert fit["pace_s_per_km"] == pytest.approx(300, abs=2)


def test_critical_speed_needs_two_performances():
    assert critical_speed([performance(5000, 1200)]) is None
    assert critical_speed([]) is None


def test_performances_outside_the_model_range_are_ignored():
    # 30 s is acceleration-dominated; 2 h is fuelling-dominated.
    fit = critical_speed(
        [performance(200, 30), performance(1500, 300), performance(30000, 7200)]
    )

    # Only the 5:00 effort survives the range filter, and one point cannot
    # define a line.
    assert fit is None


def test_warns_when_only_two_efforts_are_available():
    fit = critical_speed([performance(1500, 300), performance(4500, 1200)])

    assert any("two efforts" in warning for warning in fit["warnings"])


def test_inconsistent_performances_lower_the_fit_quality():
    fit = critical_speed(
        [
            performance(1000, 200),
            performance(5000, 1500),
            performance(10000, 2400),  # much faster per km than the 5 km
        ]
    )

    assert fit["r2"] is not None
    assert fit["r2"] < 0.99


# ---------------------------------------------------------------------------
# Fade
# ---------------------------------------------------------------------------
def test_fade_is_zero_on_an_even_run():
    # 2 km at a constant 3.333 m/s.
    points = make_points([(600, speed_for_pace(300))])

    fade = fade_index(points)

    assert fade["fade_pct"] == pytest.approx(0.0, abs=0.5)


def test_fade_detects_a_positive_split():
    # 1 km at 300 s/km, then 1 km at 400 s/km -> +33% on the second half.
    points = make_points([(300, speed_for_pace(300)), (400, speed_for_pace(400))])

    fade = fade_index(points)

    assert fade["fade_pct"] == pytest.approx(33.3, abs=2)


def test_a_negative_split_is_negative_fade():
    points = make_points([(400, speed_for_pace(400)), (300, speed_for_pace(300))])

    fade = fade_index(points)

    assert fade["fade_pct"] < 0


def test_short_runs_have_no_fade():
    points = make_points([(120, speed_for_pace(300))])  # 400 m

    assert fade_index(points, min_distance_m=8000) is None
