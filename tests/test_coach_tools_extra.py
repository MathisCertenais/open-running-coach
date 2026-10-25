"""Tests for the second batch of coach tools (load series, weights, nutrition,
period comparison) and the conditions filter on search_activities."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.coach_tools import dispatch
from tests.builders import make_activity, make_points, speed_for_pace

TODAY = date.today()


def activity_days_ago(days_ago: int, minutes: float = 60, pace: float = 300):
    start = datetime.combine(
        TODAY - timedelta(days=days_ago), time(8, 0), tzinfo=timezone.utc
    )
    points = make_points([(minutes * 60, speed_for_pace(pace))], start=start)
    return make_activity(points, activity_id=f"run-{days_ago}")


def weight(day: str, kg: float) -> dict:
    return {"id": 1, "date": day, "weight_kg": kg}


def nutrition(day: str, **overrides) -> dict:
    row = {
        "date": day,
        "macros": {"calories": 2100, "protein_g": 120, "carbs_g": 250, "fat_g": 70},
        "steps": 8000,
        "hydration_l": 2.0,
        "energy": 4,
        "appetite": 3,
        "fueling_before": True,
        "fueling_during": False,
        "fueling_after": True,
    }
    row.update(overrides)
    return row


def iso(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


# ---------------------------------------------------------------------------
# get_load_series
# ---------------------------------------------------------------------------
def test_load_series_buckets_by_week():
    context = {"activities": [activity_days_ago(1), activity_days_ago(3)]}

    result = dispatch("get_load_series", {"days": 14, "bucket": "week"}, context)

    assert result["bucket"] == "week"
    assert result["points"]
    assert sum(point["activities"] for point in result["points"]) == 2
    assert result["total_load"] > 0


def test_load_series_can_return_days():
    context = {"activities": [activity_days_ago(1)]}

    result = dispatch("get_load_series", {"days": 7, "bucket": "day"}, context)

    # The series starts at the first recorded activity, not seven days ago.
    assert len(result["points"]) <= 7
    assert result["points"][-1]["date"] == TODAY.isoformat()
    assert result["from_date"] <= result["points"][-1]["date"]


def test_load_series_carries_the_fitness_average():
    context = {"activities": [activity_days_ago(1)]}

    result = dispatch("get_load_series", {"days": 7, "bucket": "day"}, context)

    assert result["points"][-1]["ctl"] is not None
    assert result["points"][-1]["atl"] is not None


def test_load_series_caps_the_window():
    context = {"activities": [activity_days_ago(1)]}

    result = dispatch("get_load_series", {"days": 99999}, context)

    assert len(result["points"]) <= 53  # at most a year of weeks


def test_load_series_with_no_activities():
    result = dispatch("get_load_series", {}, {})

    assert result["points"] == []


# ---------------------------------------------------------------------------
# get_weights
# ---------------------------------------------------------------------------
def test_weight_trend_is_per_week():
    context = {"weights": [weight(iso(28), 73.0), weight(iso(0), 71.0)]}

    result = dispatch("get_weights", {}, context)

    assert result["change_kg"] == -2.0
    assert result["trend_kg_per_week"] == pytest.approx(-0.5, abs=0.01)


def test_weights_are_returned_oldest_first():
    context = {"weights": [weight(iso(0), 71.0), weight(iso(10), 73.0)]}

    result = dispatch("get_weights", {}, context)

    assert [point["date"] for point in result["points"]] == [iso(10), iso(0)]


def test_weight_trend_is_null_over_a_short_window():
    context = {"weights": [weight(iso(3), 72.0), weight(iso(0), 71.5)]}

    result = dispatch("get_weights", {}, context)

    assert result["trend_kg_per_week"] is None


def test_no_weight_logged_is_not_an_error():
    result = dispatch("get_weights", {}, {})

    assert result["points"] == []
    assert result["note"]


# ---------------------------------------------------------------------------
# get_nutrition
# ---------------------------------------------------------------------------
def test_nutrition_returns_days_newest_first():
    context = {"nutrition": [nutrition(iso(2)), nutrition(iso(0)), nutrition(iso(1))]}

    result = dispatch("get_nutrition", {}, context)

    dates = [day["date"] for day in result["days"]]
    assert dates == sorted(dates, reverse=True)


def test_nutrition_filters_by_date():
    context = {"nutrition": [nutrition(iso(10)), nutrition(iso(1))]}

    result = dispatch("get_nutrition", {"from_date": iso(2)}, context)

    assert result["matched"] == 1


def test_nutrition_averages_are_computed():
    context = {
        "nutrition": [
            nutrition(iso(1), macros={"calories": 2000, "protein_g": 100}),
            nutrition(iso(0), macros={"calories": 2400, "protein_g": 140}),
        ]
    }

    result = dispatch("get_nutrition", {}, context)

    assert result["average_calories"] == 2200
    assert result["average_protein_g"] == 120


def test_nutrition_caps_the_days_returned():
    context = {"nutrition": [nutrition(iso(n)) for n in range(100)]}

    result = dispatch("get_nutrition", {"limit": 999}, context)

    assert result["returned"] <= 60


# ---------------------------------------------------------------------------
# compare_periods
# ---------------------------------------------------------------------------
def test_periods_compare_the_last_n_days_with_the_previous_n():
    context = {
        "activities": [
            activity_days_ago(1),
            activity_days_ago(10),
            activity_days_ago(11),
        ]
    }

    result = dispatch("compare_periods", {"days": 7}, context)

    assert result["current"]["activities"] == 1
    assert result["comparison"]["activities"] == 2
    assert result["delta"]["activities"] == -1


def test_periods_accept_explicit_ranges():
    context = {"activities": [activity_days_ago(20)]}
    start = iso(25)
    end = iso(15)

    result = dispatch(
        "compare_periods",
        {
            "from_date": start,
            "to_date": end,
            "compare_from_date": iso(40),
            "compare_to_date": iso(30),
        },
        context,
    )

    assert result["current"]["activities"] == 1
    assert result["comparison"]["activities"] == 0


def test_periods_report_intensity_and_sessions():
    context = {
        "activities": [activity_days_ago(1)],
        "sessions": [
            {
                "date": iso(1),
                "kind": "strength",
                "title": "Legs",
                "status": "completed",
                "exercises": [],
            }
        ],
    }

    result = dispatch("compare_periods", {"days": 7}, context)

    assert result["current"]["intensity_pct"]["easy"] is not None
    assert result["current"]["sessions"]["by_kind"] == {"strength": 1}


def test_a_period_ending_before_it_starts_is_rejected():
    result = dispatch(
        "compare_periods",
        {
            "from_date": iso(0),
            "to_date": iso(10),
            "compare_from_date": iso(20),
            "compare_to_date": iso(10),
        },
        {},
    )

    assert "error" in result


# ---------------------------------------------------------------------------
# conditions filter
# ---------------------------------------------------------------------------
def test_search_filters_by_recorded_conditions():
    hot = activity_days_ago(1)
    cool = activity_days_ago(2)
    context = {
        "activities": [hot, cool],
        "feedback": {
            hot.id: {"conditions": "hot"},
            cool.id: {"conditions": "cool"},
        },
    }

    result = dispatch("search_activities", {"conditions": "hot"}, context)

    assert result["matched"] == 1
    assert result["activities"][0]["activity_id"] == hot.id


def test_a_run_without_conditions_never_matches():
    context = {"activities": [activity_days_ago(1)], "feedback": {}}

    result = dispatch("search_activities", {"conditions": "hot"}, context)

    assert result["matched"] == 0
