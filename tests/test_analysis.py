"""Tests for the activity analysis: pace zones, GAP, smoothing, GPS robustness.

These cover the data quirks documented in `AGENTS.md`: GPS jumps, missing
altitude, IDLE samples and long pauses between points.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.activity import is_moving_step, step_distance, step_speed
from app.analysis import (
    _gap_factor,
    _smooth_altitudes,
    _zone_index,
    compute_gap,
    compute_pace_zones,
    matched_runs,
    monthly_stats,
)
from app.config import (
    GAP_FACTOR_MIN,
    GAP_MAX_ABS_GRADE,
    MAX_MOVING_GAP,
    PACE_ZONES,
)
from app.parsers import TrackPoint
from tests.builders import START, make_activity, make_points, speed_for_pace


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


def test_gap_factor_follows_minetti():
    # Minetti et al. (2002): +5% costs ~30% more per metre, -5% ~24% less.
    assert _gap_factor(0.05) == pytest.approx(1.30, abs=0.02)
    assert _gap_factor(-0.05) == pytest.approx(0.76, abs=0.02)
    assert _gap_factor(0.10) == pytest.approx(1.66, abs=0.03)


def test_gap_factor_is_not_monotonic_on_steep_descents():
    # Minetti's cost curve turns back up: very steep descents cost more than
    # gentle ones, so the "downhill bonus" peaks around 20%.
    assert _gap_factor(-0.20) < _gap_factor(-0.10)
    assert _gap_factor(-0.45) > _gap_factor(-0.20)


def test_gap_grade_is_clamped_to_the_fitted_range():
    assert _gap_factor(-0.9) == pytest.approx(_gap_factor(-GAP_MAX_ABS_GRADE))
    assert _gap_factor(0.9) == pytest.approx(_gap_factor(GAP_MAX_ABS_GRADE))
    assert _gap_factor(-0.45) >= GAP_FACTOR_MIN


def test_gap_grade_is_measured_over_a_window_not_one_step():
    points = make_points([(600, 3.0)])
    spiked = [
        TrackPoint(
            lat=p.lat,
            lon=p.lon,
            time=p.time,
            speed=p.speed,
            ele=100.0 + (40.0 if i == len(points) // 2 else 0.0),
        )
        for i, p in enumerate(points)
    ]

    result = compute_gap(spiked)

    # One 40 m spike over a 3 m step is a ~1300% grade. Measured over the 50 m
    # window, after altitude smoothing, it must be an order of magnitude less.
    assert abs(result["avg_grade_pct"]) < 40


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


def test_moving_step_excludes_a_step_starting_on_an_idle_sample():
    # OpenTracks marks the moment the athlete stopped: the interval that follows
    # is the pause, even if the sensor speed is stale.
    a = TrackPoint(lat=0.0, lon=0.0, time=START, speed=3.0, ptype="IDLE")
    b = TrackPoint(lat=0.0, lon=0.00003, time=START + timedelta(seconds=1), speed=3.0)

    assert is_moving_step(a, b) is False


def test_moving_step_counts_the_step_that_arrives_at_an_idle_sample():
    a = TrackPoint(lat=0.0, lon=0.0, time=START, speed=3.0)
    b = TrackPoint(
        lat=0.0, lon=0.00003, time=START + timedelta(seconds=1), speed=3.0, ptype="IDLE"
    )

    assert is_moving_step(a, b) is True


# ---------------------------------------------------------------------------
# GAP totals
# ---------------------------------------------------------------------------
def _with_elevation(points, elevation):
    return [
        TrackPoint(
            lat=p.lat, lon=p.lon, time=p.time, speed=p.speed, ele=elevation(i, p)
        )
        for i, p in enumerate(points)
    ]


def test_compute_gap_reports_a_faster_pace_than_raw_on_a_climb():
    flat_points = _with_elevation(make_points([(600, 3.0)]), lambda i, p: 0.0)
    hill_points = _with_elevation(make_points([(600, 3.0)]), lambda i, p: i * 0.5)

    flat = compute_gap(flat_points)
    hill = compute_gap(hill_points)

    assert flat["avg_grade_pct"] == pytest.approx(0.0, abs=0.1)
    assert hill["avg_grade_pct"] > 5.0
    # Grade-adjusted pace is the flat-equivalent pace, so a climb looks faster.
    assert hill["gap_pace_s_per_km"] < flat["gap_pace_s_per_km"]


def test_compute_gap_returns_zeros_without_movement():
    result = compute_gap([])

    assert result["distance_m"] == 0
    assert result["gap_pace_s_per_km"] == 0.0
    assert result["avg_grade_pct"] == 0.0


# ---------------------------------------------------------------------------
# Matched runs
# ---------------------------------------------------------------------------
def test_matched_runs_groups_two_identical_routes():
    points = make_points([(600, 3.0)])
    first = make_activity(points, activity_id="first")
    second = make_activity(points, activity_id="second")

    groups = matched_runs([first, second])

    assert len(groups) == 1
    assert {a.id for a in groups[0]} == {"first", "second"}


def test_matched_runs_tolerates_activities_without_start_time():
    # AGENTS.md promises every consumer tolerates missing timestamps.
    points = make_points([(600, 3.0)])
    timed = make_activity(points, activity_id="timed")
    untimed = make_activity(
        [TrackPoint(lat=p.lat, lon=p.lon) for p in points], activity_id="untimed"
    )

    groups = matched_runs([timed, untimed])

    assert len(groups) == 1
    assert {a.id for a in groups[0]} == {"timed", "untimed"}


def test_matched_runs_ignores_activities_of_different_lengths():
    short = make_activity(make_points([(300, 3.0)]), activity_id="short")
    long_run = make_activity(make_points([(3000, 3.0)]), activity_id="long")

    assert matched_runs([short, long_run]) == []


# ---------------------------------------------------------------------------
# Monthly statistics
# ---------------------------------------------------------------------------
def test_monthly_stats_buckets_by_utc_month():
    # 23:30 UTC on 31 March is already April in UTC+2: the bucket must stay March.
    points = make_points(
        [(60, 3.0)], start=datetime(2026, 3, 31, 23, 30, tzinfo=timezone.utc)
    )

    stats = monthly_stats([make_activity(points)])

    assert len(stats) == 1
    assert stats[0]["month"] == "2026-03"


def test_monthly_stats_skips_activities_without_a_start_time():
    activity = make_activity([TrackPoint(lat=0.0, lon=0.0)])

    assert monthly_stats([activity]) == []


def test_gap_zones_classify_a_climb_by_effort_not_by_speed():
    # Flat-equivalent: 340 s/km is an easy Z2 pace. Climbing at that pace at a
    # 10% grade is really about 262 s/km of effort, i.e. threshold (Z4).
    points = make_points([(600, speed_for_pace(340))])
    stepped = []
    elevation = 0.0
    step = speed_for_pace(340)
    for point in points:
        stepped.append(
            TrackPoint(
                lat=point.lat,
                lon=point.lon,
                time=point.time,
                speed=point.speed,
                ele=elevation,
            )
        )
        elevation += step * 0.10

    raw = compute_pace_zones(points)["zones"]
    gap = compute_pace_zones(stepped, use_gap=True)["zones"]

    raw_index = max(range(len(raw)), key=lambda i: raw[i]["time_s"])
    gap_index = max(range(len(gap)), key=lambda i: gap[i]["time_s"])
    assert raw_index == 1  # easy
    assert gap_index >= 3  # threshold or harder
