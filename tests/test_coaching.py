"""Tests for the coaching models: load, fitness/fatigue/form, ACWR, intensity.

All assertions are written against the published model or against a property
that must hold for any correct implementation. Where the current code disagrees
with the literature, the test says so explicitly and is marked ``xfail`` with a
reason, so the fix lands as its own commit rather than hidden inside a feature.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app import coaching
from app.config import (
    ACWR_ACUTE_DAYS,
    ATL_TAU_DAYS,
    CTL_TAU_DAYS,
    FORM_NEUTRAL_BAND,
    PACE_ZONE_WEIGHTS,
    RIEGEL_EXPONENT,
)
from tests.builders import daily_activity, make_points, speed_for_pace


def zone_mixed_points():
    """Ten minutes in Z1, ten in Z3, ten in Z5."""
    return make_points(
        [
            (600, speed_for_pace(400)),  # Z1 Recovery
            (600, speed_for_pace(300)),  # Z3 Tempo
            (600, speed_for_pace(250)),  # Z5 VO2max
        ]
    )


# ---------------------------------------------------------------------------
# Pace-based load
# ---------------------------------------------------------------------------
def test_pace_zone_minutes_attributes_time_to_the_right_zone():
    minutes = coaching.pace_zone_minutes(zone_mixed_points())

    assert len(minutes) == len(PACE_ZONE_WEIGHTS)
    assert minutes[0] == pytest.approx(10.0, abs=0.1)  # Z1
    assert minutes[2] == pytest.approx(10.0, abs=0.1)  # Z3
    assert minutes[4] == pytest.approx(10.0, abs=0.1)  # Z5
    assert minutes[1] == pytest.approx(0.0, abs=0.1)
    assert minutes[3] == pytest.approx(0.0, abs=0.1)
    assert minutes[5] == pytest.approx(0.0, abs=0.1)
    assert sum(minutes) == pytest.approx(30.0, abs=0.2)


def test_pace_load_is_the_weighted_sum_of_zone_minutes():
    points = zone_mixed_points()
    minutes = coaching.pace_zone_minutes(points)
    expected = sum(m * w for m, w in zip(minutes, PACE_ZONE_WEIGHTS))

    assert coaching.pace_load(points) == pytest.approx(expected)


def test_pace_load_scales_linearly_with_duration():
    single = make_points([(600, speed_for_pace(300))])
    double = make_points([(1200, speed_for_pace(300))])

    assert coaching.pace_load(double) == pytest.approx(
        2 * coaching.pace_load(single), rel=0.01
    )


def test_pace_load_is_strictly_higher_in_a_faster_zone():
    easy = coaching.pace_load(make_points([(600, speed_for_pace(400))]))
    hard = coaching.pace_load(make_points([(600, speed_for_pace(250))]))

    assert hard > easy


# ---------------------------------------------------------------------------
# Session-RPE
# ---------------------------------------------------------------------------
def test_session_rpe_overrides_the_pace_based_load():
    activity = daily_activity(
        datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    )

    with_rpe = coaching.activity_load(activity, 5)
    without_rpe = coaching.activity_load(activity, None)

    assert with_rpe["source"] == "rpe"
    assert with_rpe["load"] == pytest.approx(5 * 60, abs=1)  # RPE x 60 minutes
    assert without_rpe["source"] == "pace"
    assert without_rpe["load"] > 0


def test_activity_load_reports_both_sources_for_transparency():
    activity = daily_activity(
        datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    )

    payload = coaching.activity_load(activity, 7)

    assert payload["rpe"] == 7
    assert payload["duration_min"] == pytest.approx(60.0, abs=0.5)
    assert payload["pace_load"] > 0


# ---------------------------------------------------------------------------
# CTL / ATL / TSB (Coggan performance management chart)
# ---------------------------------------------------------------------------
def test_first_day_uses_the_time_constants_directly():
    midnight = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    activity = daily_activity(midnight)
    load = coaching.activity_load(activity, 5)["load"]

    current = coaching.fitness_series([activity], {activity.id: 5})["current"]

    assert current["ctl"] == pytest.approx(load / CTL_TAU_DAYS, abs=0.2)
    assert current["atl"] == pytest.approx(load / ATL_TAU_DAYS, abs=0.2)


def test_constant_load_converges_to_that_load():
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    activities = [daily_activity(today - _days_ago(n)) for n in range(150)]

    current = coaching.fitness_series(activities, {a.id: 5 for a in activities})[
        "current"
    ]

    # CTL decays at 1/42 per day: after 150 days it is within 3% of the load.
    assert current["ctl"] == pytest.approx(300, rel=0.03)
    assert current["atl"] == pytest.approx(300, rel=0.01)
    # Equal fitness and fatigue leaves form near zero, slightly negative because
    # the load is constant rather than tapering.
    assert abs(current["tsb"]) < 15


def test_form_band_thresholds():
    assert coaching._form_band(FORM_NEUTRAL_BAND + 1) == "fresh"
    assert coaching._form_band(FORM_NEUTRAL_BAND) == "neutral"
    assert coaching._form_band(0) == "neutral"
    assert coaching._form_band(-FORM_NEUTRAL_BAND) == "neutral"
    assert coaching._form_band(-FORM_NEUTRAL_BAND - 1) == "fatigued"


# ---------------------------------------------------------------------------
# ACWR (Gabbett 2016)
# ---------------------------------------------------------------------------
def test_rolling_average_requires_a_full_window():
    assert (
        coaching._rolling_avg([10.0] * (ACWR_ACUTE_DAYS - 1), ACWR_ACUTE_DAYS) is None
    )
    assert coaching._rolling_avg(
        [10.0] * ACWR_ACUTE_DAYS, ACWR_ACUTE_DAYS
    ) == pytest.approx(10.0)


@pytest.mark.parametrize(
    "acwr, expected",
    [
        (0.0, "undertraining"),
        (0.79, "undertraining"),
        (0.8, "sweet_spot"),
        (1.0, "sweet_spot"),
        (1.29, "sweet_spot"),
        (1.3, "caution"),
        (1.49, "caution"),
        (1.5, "high_risk"),
        (2.5, "high_risk"),
    ],
)
def test_acwr_bands_follow_the_configured_thresholds(acwr, expected):
    assert coaching._acwr_band(acwr) == expected


def test_acwr_is_empty_before_a_full_chronic_window():
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    activities = [daily_activity(today - _days_ago(n)) for n in range(3)]

    series = coaching.acwr_series(activities, {a.id: 5 for a in activities})

    assert series["current"] is None
    assert all(day["band"] == "no_data" for day in series["days"])


# ---------------------------------------------------------------------------
# Intensity distribution (Seiler 2010)
# ---------------------------------------------------------------------------
def test_zone_groups_map_z1_z2_to_easy_z3_to_moderate_and_z4_z6_to_hard():
    groups = coaching._zone_group_totals(zone_mixed_points())

    assert groups["easy"]["time_s"] == pytest.approx(600, abs=10)  # Z1
    assert groups["moderate"]["time_s"] == pytest.approx(600, abs=10)  # Z3
    assert groups["hard"]["time_s"] == pytest.approx(600, abs=10)  # Z5


def test_finalize_groups_reports_percentages_that_sum_to_one_hundred():
    points = zone_mixed_points()
    result = coaching._finalize_groups(coaching._zone_group_totals(points), 28)

    total = sum(g["time_pct"] for g in result["groups"].values())

    assert total == pytest.approx(100.0, abs=0.2)
    assert result["window_days"] == 28


# ---------------------------------------------------------------------------
# VO2max and race prediction
# ---------------------------------------------------------------------------
def test_riegel_uses_the_published_exponent():
    assert coaching._riegel(5000, 1200, 5000) == pytest.approx(1200)
    assert coaching._riegel(5000, 1200, 10000) == pytest.approx(
        1200 * 2**RIEGEL_EXPONENT
    )


def test_riegel_slows_down_over_longer_distances():
    marathon = coaching._riegel(5000, 1200, 42195)

    # 20:00 for 5 km predicts about 3h12 for a marathon (Riegel, exponent 1.06).
    assert marathon == pytest.approx(11510, abs=60)
    # Pace must be slower over the marathon than over the 5 km.
    assert marathon / 42195 > 1200 / 5000


def test_vdot_improves_as_the_time_improves():
    faster = coaching._vdot(5000, 1200)
    slower = coaching._vdot(5000, 1800)

    assert faster > slower > 0


def test_vdot_for_a_20_minute_5k_is_in_the_daniels_range():
    vdot = coaching._vdot(5000, 1200)

    # Daniels' table: 5 km in 19:57 corresponds to VDOT 50, so 20:00 sits just
    # under 50. A result near 46 would mean the %VO2max term is wrong.
    assert 49.0 <= vdot <= 51.0


def test_vdot_rejects_invalid_input():
    assert coaching._vdot(0, 1200) is None
    assert coaching._vdot(5000, 0) is None
    assert coaching._vdot(-1, -1) is None


def _days_ago(n: int):
    from datetime import timedelta

    return timedelta(days=n)
