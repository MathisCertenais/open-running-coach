"""Tests for the coach's read-only tools."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app import coach_tools
from app.coach_tools import dispatch
from tests.builders import make_activity, make_points, speed_for_pace

BASE = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)


def run(day_offset: int, minutes: float = 60, pace: float = 300):
    points = make_points(
        [(minutes * 60, speed_for_pace(pace))],
        start=BASE + timedelta(days=day_offset),
    )
    return make_activity(points, activity_id=f"run-{day_offset}")


def context(**overrides):
    data = {
        "activities": [
            run(0, minutes=30, pace=330),
            run(1, minutes=60, pace=300),
            run(2, minutes=120, pace=360),
        ],
        "rpe": {"run-0": 4},
        "feedback": {
            "run-1": {"pain": True, "pain_location": "knee", "pain_severity": 5}
        },
        "notes": {"run-1": "felt heavy"},
        "sessions": [
            {
                "id": 1,
                "date": "2026-03-02",
                "kind": "strength",
                "title": "Lower body",
                "duration_min": 50,
                "rpe": 8,
                "status": "completed",
                "exercises": [{"name": "Leg press", "sets": 3, "reps": 10}],
            }
        ],
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# search_activities
# ---------------------------------------------------------------------------
def test_search_returns_newest_first():
    result = dispatch("search_activities", {"limit": 5}, context())

    dates = [row["date"] for row in result["activities"]]
    assert dates == sorted(dates, reverse=True)


def test_search_filters_by_distance():
    result = dispatch("search_activities", {"min_distance_km": 10}, context())

    assert result["matched"] == 2
    assert all(row["distance_km"] >= 5 for row in result["activities"])


def test_search_filters_by_date():
    result = dispatch(
        "search_activities",
        {"from_date": "2026-03-02", "to_date": "2026-03-02"},
        context(),
    )

    assert result["matched"] == 1


def test_search_caps_the_limit():
    result = dispatch("search_activities", {"limit": 999}, context())

    assert result["returned"] <= coach_tools.MAX_ROWS


def test_search_includes_rpe():
    result = dispatch("search_activities", {}, context())

    by_id = {row["activity_id"]: row for row in result["activities"]}
    assert by_id["run-0"]["rpe"] == 4
    assert by_id["run-1"]["rpe"] is None


def test_search_never_leaks_coordinates():
    payload = json.dumps(dispatch("search_activities", {}, context()))

    assert "lat" not in payload
    assert "lon" not in payload


# ---------------------------------------------------------------------------
# get_activity
# ---------------------------------------------------------------------------
def test_activity_detail_includes_the_checkin():
    result = dispatch("get_activity", {"activity_id": "run-1"}, context())

    assert result["distance_km"] == pytest.approx(12, abs=0.1)
    assert result["pain"]["reported"] is True
    assert result["pain"]["location"] == "knee"
    assert result["note"] == "felt heavy"


def test_activity_detail_has_splits():
    result = dispatch("get_activity", {"activity_id": "run-2"}, context())

    assert len(result["splits"]) == 12  # capped at 12 kilometres
    assert all("pace_s_per_km" in split for split in result["splits"])


def test_unknown_activity_returns_an_error_not_an_exception():
    result = dispatch("get_activity", {"activity_id": "nope"}, context())

    assert "error" in result


# ---------------------------------------------------------------------------
# best_efforts
# ---------------------------------------------------------------------------
def test_best_efforts_lists_one_per_distance():
    result = dispatch("best_efforts", {}, context())

    distances = [item["distance_km"] for item in result["efforts"]]
    assert distances == sorted(distances)
    assert 5.0 in distances


def test_best_efforts_for_one_distance_returns_the_fastest_first():
    result = dispatch("best_efforts", {"distance_km": 5}, context())

    times = [item["time_s"] for item in result["efforts"]]
    assert times == sorted(times)


def test_best_efforts_without_data_is_not_an_error():
    result = dispatch("best_efforts", {}, context(activities=[]))

    assert result["efforts"] == []


# ---------------------------------------------------------------------------
# get_sessions
# ---------------------------------------------------------------------------
def test_sessions_include_exercises():
    result = dispatch("get_sessions", {}, context())

    assert result["matched"] == 1
    assert result["sessions"][0]["exercises"][0]["name"] == "Leg press"


def test_sessions_filter_by_kind():
    result = dispatch("get_sessions", {"kind": "mobility"}, context())

    assert result["matched"] == 0


def test_sessions_filter_by_date():
    result = dispatch("get_sessions", {"from_date": "2026-03-10"}, context())

    assert result["matched"] == 0


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------
def test_unknown_tool_is_reported_to_the_model():
    assert "error" in dispatch("drop_database", {}, context())


def test_a_broken_tool_argument_does_not_crash():
    assert "error" in dispatch(
        "search_activities", {"from_date": "not-a-date"}, context()
    )


def test_every_schema_has_a_handler():
    names = {schema["function"]["name"] for schema in coach_tools.TOOL_SCHEMAS}

    assert names == set(coach_tools._HANDLERS)
