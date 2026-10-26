"""Tests for the second batch of coach tools (load series, weights, nutrition,
period comparison) and the conditions filter on search_activities."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.coach_tools import dispatch
from tests.builders import make_activity, make_points, speed_for_pace

TODAY = date.today()


def pinned(**context) -> dict:
    """A tool context with the clock pinned to ``TODAY``.

    ``_today()`` reads the clock when the context does not carry ``today``, so
    a test that models "today" as a wall-clock read is flaky across midnight.
    Every context a clock-reading tool receives names the day explicitly.
    """
    return {"today": TODAY.isoformat(), **context}


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
    context = pinned(activities=[activity_days_ago(1), activity_days_ago(3)])

    result = dispatch("get_load_series", {"days": 14, "bucket": "week"}, context)

    assert result["bucket"] == "week"
    assert result["points"]
    assert sum(point["activities"] for point in result["points"]) == 2
    assert result["total_load"] > 0


def test_load_series_can_return_days():
    context = pinned(activities=[activity_days_ago(1)])

    result = dispatch("get_load_series", {"days": 7, "bucket": "day"}, context)

    # The series starts at the first recorded activity, not seven days ago.
    assert len(result["points"]) <= 7
    assert result["points"][-1]["date"] == TODAY.isoformat()
    assert result["from_date"] <= result["points"][-1]["date"]


def test_load_series_honours_the_pinned_day():
    """The context's ``today`` wins over the wall clock (the bench pin)."""
    future = TODAY + timedelta(days=5)

    context = {"today": future.isoformat(), "activities": [activity_days_ago(1)]}
    result = dispatch("get_load_series", {"days": 30, "bucket": "day"}, context)

    assert result["points"][-1]["date"] == future.isoformat()


def test_load_series_carries_the_fitness_average():
    context = pinned(activities=[activity_days_ago(1)])

    result = dispatch("get_load_series", {"days": 7, "bucket": "day"}, context)

    assert result["points"][-1]["ctl"] is not None
    assert result["points"][-1]["atl"] is not None


def test_load_series_caps_the_window():
    context = pinned(activities=[activity_days_ago(1)])

    result = dispatch("get_load_series", {"days": 99999}, context)

    assert len(result["points"]) <= 53  # at most a year of weeks


def test_load_series_with_no_activities():
    result = dispatch("get_load_series", {}, pinned())

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
    context = pinned(
        activities=[
            activity_days_ago(1),
            activity_days_ago(10),
            activity_days_ago(11),
        ]
    )

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
    context = pinned(
        activities=[activity_days_ago(1)],
        sessions=[
            {
                "date": iso(1),
                "kind": "strength",
                "title": "Legs",
                "status": "completed",
                "exercises": [],
            }
        ],
    )

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


# ---------------------------------------------------------------------------
# get_shoes
# ---------------------------------------------------------------------------
def shoe(shoe_id: int, name: str, km: float, threshold: float = 800, retired=False):
    return {
        "id": shoe_id,
        "name": name,
        "notes": "",
        "threshold_km": threshold,
        "retired": retired,
        "distance_m": km * 1000,
        "activities_count": 10,
    }


def test_shoes_are_ordered_by_mileage():
    context = {"shoes": [shoe(1, "A", 100), shoe(2, "B", 600)]}

    result = dispatch("get_shoes", {}, context)

    assert [item["name"] for item in result["shoes"]] == ["B", "A"]


def test_shoes_report_the_share_of_the_threshold():
    context = {"shoes": [shoe(1, "A", 400, threshold=800)]}

    result = dispatch("get_shoes", {}, context)

    assert result["shoes"][0]["percent_of_threshold"] == 50.0


def test_retired_shoes_are_hidden_unless_asked_for():
    context = {"shoes": [shoe(1, "Live", 100), shoe(2, "Old", 900, retired=True)]}

    assert len(dispatch("get_shoes", {}, context)["shoes"]) == 1
    assert len(dispatch("get_shoes", {"include_retired": True}, context)["shoes"]) == 2


# ---------------------------------------------------------------------------
# get_plan
# ---------------------------------------------------------------------------
def plan_context(start_days_ago: int = 14):
    start = (TODAY - timedelta(days=start_days_ago)).isoformat()
    weeks = [
        {
            "week": number,
            "type": "build",
            "volume_min": 300 + number * 10,
            "sessions": [
                {
                    "type": "easy",
                    "duration_min": 60,
                    "distance_km": 10.0,
                    "zones": "Z2",
                }
            ],
        }
        for number in range(1, 5)
    ]
    return {
        "today": TODAY.isoformat(),
        "plans": [
            {
                "id": 7,
                "name": "Spring half",
                "goal_description": "Half on 2026-05-01",
                "weeks": 4,
                "data": {
                    "start_date": start,
                    "weeks_plan": weeks,
                    "projection": {"start_ctl": 20, "final_ctl": 45, "peak_ctl": 47},
                },
            }
        ],
    }


def test_plan_without_any_plan_says_so():
    result = dispatch("get_plan", {}, {})

    assert result["plan"] is None
    assert result["note"]


def test_plan_reports_the_current_week():
    result = dispatch("get_plan", {}, plan_context(start_days_ago=14))

    assert result["plan_id"] == 7
    assert result["current_week"] == 3
    assert result["this_week"]["week"] == 3
    assert result["next_week"]["week"] == 4
    assert result["weeks_remaining"] == 1


def test_plan_current_week_is_clamped_to_the_plan_length():
    result = dispatch("get_plan", {}, plan_context(start_days_ago=400))

    assert result["current_week"] == 4
    assert result["weeks_remaining"] == 0


def test_plan_passes_the_projection_through():
    result = dispatch("get_plan", {}, plan_context())

    assert result["projection"]["final_ctl"] == 45


def test_plan_can_be_selected_by_id():
    context = plan_context()
    context["plans"].insert(
        0,
        {
            "id": 9,
            "name": "Newer",
            "goal_description": "",
            "weeks": 4,
            "data": {"weeks_plan": [], "start_date": None},
        },
    )

    assert dispatch("get_plan", {}, context)["plan_id"] == 9
    assert dispatch("get_plan", {"plan_id": 7}, context)["plan_id"] == 7


# ---------------------------------------------------------------------------
# get_injuries
# ---------------------------------------------------------------------------
def injury_context():
    run_day = activity_days_ago(1)
    session_day = (TODAY - timedelta(days=2)).isoformat()
    return {
        "today": TODAY.isoformat(),
        "activities": [run_day],
        "feedback": {
            run_day.id: {
                "pain": True,
                "pain_location": "knee",
                "pain_side": "left",
                "pain_severity": 6,
                "pain_trend": "same",
                "pain_timing": "next_morning",
            }
        },
        "sessions": [
            {
                "id": 1,
                "date": session_day,
                "kind": "strength",
                "title": "Lower body",
                "rpe": 8,
                "status": "completed",
                "exercises": [{"name": "Leg press", "sets": 3, "reps": 10}],
            }
        ],
        "verdicts": {},
    }


def test_injuries_return_episodes_with_their_links():
    result = dispatch("get_injuries", {}, injury_context())

    assert result["count"] == 1
    assert result["episodes"][0]["location"] == "knee"
    assert result["links"]
    assert result["links"][0]["session_title"] == "Lower body"
    assert "base_rate" in result["summary"]


def test_injuries_can_filter_by_location():
    context = injury_context()

    assert dispatch("get_injuries", {"location": "knee"}, context)["count"] == 1
    assert dispatch("get_injuries", {"location": "achilles"}, context)["count"] == 0


def test_injuries_can_show_only_active_episodes():
    context = injury_context()

    assert dispatch("get_injuries", {"active_only": True}, context)["count"] == 1
    assert dispatch("get_injuries", {"active_only": False}, context)["count"] == 1


def test_injuries_attach_a_verdict_when_one_exists():
    context = injury_context()
    context["verdicts"] = {
        ("knee", "left", (TODAY - timedelta(days=1)).isoformat()): "plausible"
    }

    result = dispatch("get_injuries", {}, context)

    assert result["episodes"][0]["verdict"] == "plausible"


def test_no_pain_means_no_episodes():
    result = dispatch("get_injuries", {}, pinned(activities=[], feedback={}))

    assert result["count"] == 0
    assert result["episodes"] == []
