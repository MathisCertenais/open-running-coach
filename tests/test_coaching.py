"""Tests for the coaching models: load, fitness/fatigue/form, ACWR, intensity,
VO2max and plan generation.

Dates are always passed explicitly (``today=``, ``start_date=``) so the suite
never depends on the wall clock or on the machine's time zone.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app import coaching
from app.config import (
    ACWR_ACUTE_DAYS,
    ATL_TAU_DAYS,
    CTL_TAU_DAYS,
    FORM_NEUTRAL_BAND,
    PACE_ZONE_WEIGHTS,
    PLAN_DELOAD_EVERY,
    PLAN_DELOAD_FACTOR,
    PLAN_MAX_SESSIONS,
    PLAN_MIN_SESSIONS,
    PLAN_PROGRESSION,
    RIEGEL_EXPONENT,
)
from tests.builders import daily_activity, make_activity, make_points, speed_for_pace

TODAY = date(2026, 3, 30)


def at(day: date, hour: int = 6) -> datetime:
    """A UTC timestamp on a given day."""
    return datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)


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
    activity = daily_activity(at(TODAY))

    with_rpe = coaching.activity_load(activity, 5)
    without_rpe = coaching.activity_load(activity, None)

    assert with_rpe["source"] == "rpe"
    assert with_rpe["load"] == pytest.approx(5 * 60, abs=1)  # RPE x 60 minutes
    assert without_rpe["source"] == "pace"
    assert without_rpe["load"] > 0


def test_activity_load_reports_both_sources_for_transparency():
    payload = coaching.activity_load(daily_activity(at(TODAY)), 7)

    assert payload["rpe"] == 7
    assert payload["duration_min"] == pytest.approx(60.0, abs=0.5)
    assert payload["pace_load"] > 0


def test_zero_duration_activity_falls_back_to_pace_load():
    # An activity with no movement has no session length to multiply by RPE.
    activity = make_activity([], activity_id="empty")

    payload = coaching.activity_load(activity, 8)

    assert payload["source"] == "pace"
    assert payload["duration_min"] == 0


# ---------------------------------------------------------------------------
# Daily series and load source labelling
# ---------------------------------------------------------------------------
def test_daily_source_is_pace_when_no_rpe_is_logged():
    activity = daily_activity(at(TODAY))

    series = coaching.full_load_series([activity], {}, today=TODAY)

    assert series[-1]["source"] == "pace"
    assert series[-1]["has_rpe"] is False


def test_daily_source_is_mixed_when_a_day_has_both_kinds():
    morning = daily_activity(at(TODAY, 6), activity_id="morning")
    evening = daily_activity(at(TODAY, 18), activity_id="evening")

    series = coaching.full_load_series([morning, evening], {"morning": 5}, today=TODAY)

    assert series[-1]["source"] == "mixed"
    assert series[-1]["activities"] == 2


def test_daily_source_is_null_on_a_rest_day():
    activity = daily_activity(at(TODAY - timedelta(days=3)))

    series = coaching.full_load_series([activity], {activity.id: 5}, today=TODAY)

    rest_days = [d for d in series if d["activities"] == 0]
    assert rest_days
    assert all(d["source"] is None for d in rest_days)
    assert all(d["load"] == 0 for d in rest_days)


# ---------------------------------------------------------------------------
# CTL / ATL / TSB (Coggan performance management chart)
# ---------------------------------------------------------------------------
def test_first_day_uses_the_time_constants_directly():
    activity = daily_activity(at(TODAY))
    load = coaching.activity_load(activity, 5)["load"]

    current = coaching.fitness_series([activity], {activity.id: 5}, today=TODAY)[
        "current"
    ]

    assert current["ctl"] == pytest.approx(load / CTL_TAU_DAYS, abs=0.2)
    assert current["atl"] == pytest.approx(load / ATL_TAU_DAYS, abs=0.2)


def test_constant_load_converges_to_that_load():
    activities = [
        daily_activity(at(TODAY - timedelta(days=n)), activity_id=f"run-{n}")
        for n in range(150)
    ]

    current = coaching.fitness_series(
        activities, {a.id: 5 for a in activities}, today=TODAY
    )["current"]

    # CTL decays at 1/42 per day: after 150 days it is within 3% of the load.
    assert current["ctl"] == pytest.approx(300, rel=0.03)
    assert current["atl"] == pytest.approx(300, rel=0.01)
    assert abs(current["tsb"]) < 15


def test_fatigue_drains_faster_than_fitness():
    activities = [daily_activity(at(TODAY - timedelta(days=10)), activity_id="one")]

    days = coaching.fitness_series(activities, {activities[0].id: 8}, today=TODAY)[
        "days"
    ]

    peak = days[0]
    last = days[-1]
    # Both decay after the session, but fatigue loses a much larger share of its
    # peak than fitness does (time constants 7 vs 42 days).
    assert last["atl"] / peak["atl"] < last["ctl"] / peak["ctl"]
    assert last["atl"] < peak["atl"]
    assert last["ctl"] < peak["ctl"]


def test_form_is_calibrating_until_it_has_enough_history():
    activity = daily_activity(at(TODAY), activity_id="one")

    series = coaching.fitness_series([activity], {"one": 5}, today=TODAY)

    assert series["current"]["calibrating"] is True
    assert series["current"]["form"] == "calibrating"


def test_form_leaves_calibration_after_the_configured_window():
    activities = [
        daily_activity(at(TODAY - timedelta(days=50 - n)), activity_id=f"run-{n}")
        for n in range(51)
    ]

    series = coaching.fitness_series(activities, {}, today=TODAY)
    current = series["current"]

    assert current["calibrating"] is False
    assert current["form"] in {"fresh", "neutral", "fatigued"}


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
        (0.0, "ramping_down"),
        (0.79, "ramping_down"),
        (0.8, "steady"),
        (1.0, "steady"),
        (1.29, "steady"),
        (1.3, "ramping_up"),
        (1.49, "ramping_up"),
        (1.5, "sharp_increase"),
        (2.5, "sharp_increase"),
    ],
)
def test_acwr_bands_follow_the_configured_thresholds(acwr, expected):
    assert coaching._acwr_band(acwr) == expected


def test_acwr_is_empty_before_a_full_chronic_window():
    activities = [
        daily_activity(at(TODAY - timedelta(days=n)), activity_id=f"run-{n}")
        for n in range(3)
    ]

    series = coaching.acwr_series(activities, {}, today=TODAY)

    assert series["current"] is None
    assert all(day["band"] == "no_data" for day in series["days"])


def test_acwr_is_one_when_the_load_is_constant():
    activities = [
        daily_activity(at(TODAY - timedelta(days=n)), activity_id=f"run-{n}")
        for n in range(40)
    ]

    current = coaching.acwr_series(
        activities, {a.id: 5 for a in activities}, today=TODAY
    )["current"]

    assert current is not None
    assert current["acwr"] == pytest.approx(1.0, abs=0.02)
    assert current["band"] == "steady"


def test_acwr_flags_a_sudden_load_increase():
    # Four quiet weeks, then one hard week. The chronic window is the 28 days
    # *before* the hard week, so it must be fully covered by the quiet block.
    quiet = [
        daily_activity(
            at(TODAY - timedelta(days=34 - n)),
            rpe=5,
            duration_s=1200,
            activity_id=f"q{n}",
        )
        for n in range(28)
    ]
    hard = [
        daily_activity(
            at(TODAY - timedelta(days=6 - n)),
            rpe=5,
            duration_s=3600,
            activity_id=f"h{n}",
        )
        for n in range(7)
    ]

    current = coaching.acwr_series(quiet + hard, {}, today=TODAY)["current"]

    assert current is not None
    assert current["acwr"] == pytest.approx(3.0, abs=0.1)
    assert current["band"] == "sharp_increase"


def test_acwr_excludes_the_acute_week_from_the_baseline():
    # 28 quiet days at 100, then a week at 300: a coupled baseline (which
    # includes the acute week) would read 1.8, the uncoupled one reads 3.0.
    activities = [
        daily_activity(
            at(TODAY - timedelta(days=34 - n)),
            rpe=5,
            duration_s=1200,
            activity_id=f"q{n}",
        )
        for n in range(28)
    ] + [
        daily_activity(
            at(TODAY - timedelta(days=6 - n)),
            rpe=5,
            duration_s=3600,
            activity_id=f"h{n}",
        )
        for n in range(7)
    ]

    current = coaching.acwr_series(activities, {}, today=TODAY)["current"]

    coupled = 300 / ((21 * 100 + 7 * 300) / 28)
    assert current["acwr"] == pytest.approx(3.0, abs=0.1)
    assert current["acwr"] != pytest.approx(coupled, abs=0.2)


def test_acwr_is_suppressed_after_a_training_gap():
    # Training ends ten days before "today": long enough to stop reading.
    activities = [
        daily_activity(at(TODAY - timedelta(days=30 - n)), activity_id=f"run-{n}")
        for n in range(21)
    ]

    current = coaching.acwr_series(
        activities, {a.id: 5 for a in activities}, today=TODAY
    )
    last = current["days"][-1]

    assert last["gap_days"] > 7
    assert last["acwr"] is None
    assert last["band"] == "after_gap"


# ---------------------------------------------------------------------------
# Intensity distribution (Seiler 2010)
# ---------------------------------------------------------------------------
def test_zone_groups_map_z1_z2_to_easy_z3_to_moderate_and_z4_z6_to_hard():
    groups = coaching._zone_group_totals(zone_mixed_points())

    assert groups["easy"]["time_s"] == pytest.approx(600, abs=10)  # Z1
    assert groups["moderate"]["time_s"] == pytest.approx(600, abs=10)  # Z3
    assert groups["hard"]["time_s"] == pytest.approx(600, abs=10)  # Z5


def test_finalize_groups_reports_percentages_that_sum_to_one_hundred():
    result = coaching._finalize_groups(
        coaching._zone_group_totals(zone_mixed_points()), 28
    )

    total = sum(g["time_pct"] for g in result["groups"].values())

    assert total == pytest.approx(100.0, abs=0.2)
    assert result["window_days"] == 28


def test_finalize_groups_survives_an_empty_window():
    empty = {
        name: {"time_s": 0.0, "distance_m": 0.0}
        for name in ("easy", "moderate", "hard")
    }

    result = coaching._finalize_groups(empty, 7)

    assert all(g["time_pct"] == 0.0 for g in result["groups"].values())
    assert result["total_time_s"] == 0.0


def test_intensity_distribution_returns_weekly_and_rolling_windows():
    points = zone_mixed_points()

    result = coaching.intensity_distribution([make_activity(points)])

    assert result["weekly"]["window_days"] == 7
    assert result["rolling"]["window_days"] == 28
    assert set(result["target"]) == {"easy", "moderate", "hard"}


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


def test_vo2max_uses_the_best_effort_as_the_seed():
    # A 5.2 km effort so that a 5 km best effort exists inside it.
    points = make_points([(1250, speed_for_pace(240))])
    activity = make_activity(points)

    result = coaching.vo2max_and_predictions([activity])

    assert result["effective_vo2max"] == pytest.approx(49.8, abs=1.5)
    assert result["seed"]["distance_m"] == pytest.approx(5000, rel=0.05)
    labels = [p["label"] for p in result["predictions"]]
    assert "5K" in labels or "5 km" in labels


def test_vo2max_is_empty_without_activities():
    assert coaching.vo2max_and_predictions([])["effective_vo2max"] is None


# ---------------------------------------------------------------------------
# Plan generation (periodisation)
# ---------------------------------------------------------------------------
def make_plan(**kwargs):
    kwargs.setdefault("weekly_target_s", 36000)  # 600 minutes per week
    kwargs.setdefault("sessions_per_week", 4)
    kwargs.setdefault("start_date", "2026-03-02")
    return coaching.generate_plan([], **kwargs)


def test_plan_respects_the_session_count_bounds():
    plan = make_plan(sessions_per_week=4)

    for week in plan["weeks_plan"]:
        assert PLAN_MIN_SESSIONS <= len(week["sessions"]) <= PLAN_MAX_SESSIONS


def test_plan_clamps_out_of_range_session_counts():
    assert make_plan(sessions_per_week=1)["sessions_per_week"] == PLAN_MIN_SESSIONS
    assert make_plan(sessions_per_week=12)["sessions_per_week"] == PLAN_MAX_SESSIONS


def test_plan_progresses_by_about_ten_percent_before_a_deload():
    plan = make_plan()
    volumes = [w["volume_min"] for w in plan["weeks_plan"]]

    assert volumes[1] / volumes[0] == pytest.approx(PLAN_PROGRESSION, rel=0.05)
    deload_index = PLAN_DELOAD_EVERY - 1
    assert plan["weeks_plan"][deload_index]["type"] == "deload"
    assert volumes[deload_index] < volumes[deload_index - 1]


def test_plan_never_exceeds_the_peak_volume():
    plan = make_plan()

    assert all(w["volume_min"] <= plan["peak_weekly_min"] for w in plan["weeks_plan"])


def test_deload_week_matches_the_configured_factor():
    plan = make_plan()
    volumes = [w["volume_min"] for w in plan["weeks_plan"]]
    index = PLAN_DELOAD_EVERY - 1

    assert plan["weeks_plan"][index]["type"] == "deload"
    # A deload steps back to a fixed fraction of the previous build week.
    assert volumes[index] / volumes[index - 1] == pytest.approx(
        PLAN_DELOAD_FACTOR, abs=0.02
    )


def test_plan_length_comes_from_the_goal_date():
    plan = make_plan(goal_distance_m=21097.5, goal_date="2026-05-25")

    # 2026-03-02 -> 2026-05-25 is exactly 12 weeks.
    assert plan["weeks"] == 12


def test_plan_schedules_support_sessions_with_dates():
    plan = make_plan()

    assert plan["support_sessions"]
    assert all("date" in s for s in plan["support_sessions"])
    assert plan["support_sessions"][0]["date"] == plan["start_date"]


def test_taper_week_drops_strength_sessions():
    plan = make_plan()
    last_week = plan["weeks"]

    kinds = [s["kind"] for s in plan["support_sessions"] if s["week"] == last_week]

    assert "strength" not in kinds
    assert kinds  # mobility and rest remain


def test_plan_names_its_goal():
    plan = make_plan(goal_distance_m=42195, goal_date="2026-06-01")

    assert "marathon" in plan["goal_description"].lower()
    assert plan["name"] == "Training plan"


# ---------------------------------------------------------------------------
# Load divergence and plan projection
# ---------------------------------------------------------------------------
def test_divergence_flags_a_run_that_felt_harder_than_the_pace():
    activity = daily_activity(at(TODAY), activity_id="hard-feeling")

    flagged = coaching.load_divergence([activity], {"hard-feeling": 10})

    assert len(flagged) == 1
    assert flagged[0]["direction"] == "harder"
    assert flagged[0]["ratio"] > 1.4


def test_divergence_ignores_a_run_that_matches_its_pace():
    activity = daily_activity(at(TODAY), activity_id="honest")

    # A 60-minute tempo run carries a pace load of about 180: RPE 3 matches it.
    assert coaching.load_divergence([activity], {"honest": 3}) == []


def test_divergence_ignores_runs_without_rpe():
    activity = daily_activity(at(TODAY), activity_id="no-rpe")

    assert coaching.load_divergence([activity], {}) == []


def test_projection_raises_chronic_load_through_a_plan():
    plan = make_plan()

    projection = coaching.project_plan(plan, 20.0)

    assert len(projection["weeks"]) == plan["weeks"]
    assert projection["start_ctl"] == 20.0
    assert projection["final_ctl"] > projection["start_ctl"]
    assert projection["peak_ctl"] >= projection["final_ctl"] - 0.2


def test_projection_dips_on_deload_weeks():
    plan = make_plan()

    weeks = coaching.project_plan(plan, 40.0)["weeks"]
    builds = [w for w in weeks if w["type"] == "build"]
    deloads = [w for w in weeks if w["type"] == "deload"]

    assert builds and deloads
    assert max(w["weekly_load"] for w in builds) > max(
        w["weekly_load"] for w in deloads
    )
