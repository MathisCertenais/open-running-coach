"""Tool handlers take their clock from the context when it is pinned."""

from __future__ import annotations

from datetime import datetime, timezone

from app.coach_tools import dispatch
from tests.builders import daily_activity


def _activity(day: datetime, activity_id: str = "run-1"):
    return daily_activity(day, activity_id=activity_id)


def test_pinned_today_drives_get_plan():
    plan = {
        "id": 1,
        "name": "Build",
        "goal_description": "Race: 10 km on 2026-04-01",
        "weeks": 4,
        "data": {
            "start_date": "2026-03-02",
            "weeks_plan": [
                {
                    "week": number,
                    "type": "build",
                    "volume_min": 200,
                    "sessions": [],
                }
                for number in range(1, 5)
            ],
        },
    }
    context = {"plans": [plan], "today": "2026-03-16"}

    result = dispatch("get_plan", {}, context)

    assert result["current_week"] == 3
    assert result["weeks_remaining"] == 1


def test_pinned_today_drives_get_injuries():
    activity = _activity(datetime(2026, 3, 10, 8, 0, tzinfo=timezone.utc))
    context = {
        "activities": [activity],
        "feedback": {
            activity.id: {
                "pain": True,
                "pain_location": "knee",
                "pain_side": "right",
                "pain_severity": 5,
            }
        },
        "today": "2026-03-12",
    }

    active = dispatch("get_injuries", {}, context)
    stale = dispatch("get_injuries", {}, {**context, "today": "2026-06-01"})

    assert active["episodes"][0]["active"] is True
    assert stale["episodes"][0]["active"] is False


def test_pinned_today_drives_the_load_series():
    activity = _activity(datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc))
    context = {"activities": [activity], "rpe": {}, "today": "2026-03-10"}

    result = dispatch("get_load_series", {"bucket": "day"}, context)

    assert result["from_date"] == "2026-03-01"
    assert result["to_date"] == "2026-03-10"
    assert len(result["points"]) == 10
