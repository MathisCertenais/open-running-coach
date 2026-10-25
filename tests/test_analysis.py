"""Tests for the activity analysis: pace zones, GAP, smoothing, GPS robustness.

These cover the data quirks documented in `AGENTS.md`: GPS jumps, missing
altitude, IDLE samples and long pauses between points.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.activity import is_moving_step, step_distance, step_speed
from app.analysis import (
    _gap_factor,
    _smooth_altitudes,
    _zone_index,
    compute_pace_zones,
)
from app.config import (
    GAP_DOWNHILL_FACTOR,
    GAP_MAX_DOWN_GRADE,
    GAP_UPHILL_FACTOR,
    MAX_MOVING_GAP,
    PACE_ZONES,
)
from app.parsers import TrackPoint
from tests.builders import START, make_points, speed_for_pace


# ---------------------------------------------------------------------------
# Zone classification
# ---------------------------------------------------------------------------
def test_zone_index_uses_half_open_bounds():
    # Z1 is unbounded above: anything slower than 390 s/km is recovery.
    assert _zone_index(400) == 0
    assert _zone_index(390) == 0
    assert _zone_index(389.9) == 1
    assert _zone_index(330) == 1
    # 290 s/km opens Z3; 289.9 falls into Z4 (threshold).
    assert _zone_index(290) == 2
    assert _zone_index(289.9) == 3
    assert _zone_index(229.9) == 5
    # Z6 is the fastest zone and is unbounded below.
    assert _zone_index(0) == 5


def test_every_pace_has_a_zone():
    for pace in range(0, 900):
        assert _zone_index(float(pace)) is not None


def test_pace_zone_totals_match_the_moving_time():
    points = make_points(
        [
            (600, speed_for_pace(400)),
            (600, speed_for_pace(300)),
            (600, speed_for_pace(250)),
        ]
    )

    result = compute_pace_zones(points)
    zone_time = sum(z["time_s"] for z in result["zones"])

    assert result["total_time_s"] == pytest.approx(1800, abs=5)
    assert zone_time == pytest.approx(result["total_time_s"], abs=0.5)
    assert len(result["zones"]) == len(PACE_ZONES)


def test_pace_zone_percentages_sum_to_one_hundred():
    points = make_points([(300, speed_for_pace(400)), (300, speed_for_pace(250))])

    result = compute_pace_zones(points)

    assert sum(z["percent"] for z in result["zones"]) == pytest.approx(100.0, abs=0.5)


# ---------------------------------------------------------------------------
# GAP
# ---------------------------------------------------------------------------
def test_gap_factor_is_one_on_the_flat():
    assert _gap_factor(None) == 1.0
    assert _gap_factor(0.0) == 1.0


def test_gap_factor_increases_uphill_and_decreases_downhill():
    assert _gap_factor(0.05) == pytest.approx(1 + GAP_UPHILL_FACTOR * 0.05)
    assert _gap_factor(-0.05) == pytest.approx(1 + GAP_DOWNHILL_FACTOR * -0.05)


def test_gap_factor_caps_the_descent_bonus():
    steep = _gap_factor(-0.5)
    capped = _gap_factor(-GAP_MAX_DOWN_GRADE)

    assert steep == pytest.approx(capped)


# ---------------------------------------------------------------------------
# Altitude smoothing
# ---------------------------------------------------------------------------
def test_smooth_altitudes_forward_fills_missing_values():
    smoothed = _smooth_altitudes([100.0, None, 102.0])

    assert len(smoothed) == 3
    assert smoothed[0] == pytest.approx(100.667, abs=0.01)
    assert smoothed[2] == pytest.approx(100.667, abs=0.01)


def test_smooth_altitudes_handles_a_missing_series():
    assert _smooth_altitudes([]) == []
    assert _smooth_altitudes([None, None]) == [None, None]


# ---------------------------------------------------------------------------
# GPS robustness
# ---------------------------------------------------------------------------
def test_step_distance_rejects_an_implied_speed_jump():
    # ~111 m eastwards in one second is far above MAX_IMPLIED_SPEED, so the
    # positional distance is discarded in favour of the speed sensor.
    a = TrackPoint(lat=0.0, lon=0.0, time=START, speed=3.0)
    b = TrackPoint(lat=0.0, lon=0.001, time=START + timedelta(seconds=1), speed=3.0)

    assert step_distance(a, b) == pytest.approx(3.0)


def test_step_distance_uses_positions_for_plausible_movement():
    a = TrackPoint(lat=0.0, lon=0.0, time=START, speed=3.0)
    b = TrackPoint(lat=0.0, lon=0.00003, time=START + timedelta(seconds=1), speed=3.0)

    # ~3.3 m of real movement: the positional distance wins.
    assert step_distance(a, b) == pytest.approx(3.34, abs=0.05)


def test_step_speed_falls_back_to_the_position_when_no_sensor_is_present():
    a = TrackPoint(lat=0.0, lon=0.0, time=START)
    b = TrackPoint(lat=0.0, lon=0.00003, time=START + timedelta(seconds=1))

    assert step_speed(a, b) == pytest.approx(3.34, abs=0.05)


def test_moving_step_excludes_a_long_pause():
    a = TrackPoint(lat=0.0, lon=0.0, time=START, speed=3.0)
    b = TrackPoint(
        lat=0.0,
        lon=0.0001,
        time=START + timedelta(seconds=MAX_MOVING_GAP + 1),
        speed=3.0,
    )

    assert is_moving_step(a, b) is False


def test_moving_step_excludes_a_stationary_point():
    a = TrackPoint(lat=0.0, lon=0.0, time=START, speed=0.0)
    b = TrackPoint(lat=0.0, lon=0.0, time=START + timedelta(seconds=1), speed=0.0)

    assert is_moving_step(a, b) is False


def test_moving_step_accepts_a_normal_stride():
    a = TrackPoint(lat=0.0, lon=0.0, time=START, speed=3.0)
    b = TrackPoint(lat=0.0, lon=0.00003, time=START + timedelta(seconds=1), speed=3.0)

    assert is_moving_step(a, b) is True
