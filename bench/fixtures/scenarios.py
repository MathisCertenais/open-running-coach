"""Synthetic athletes and the properties each frozen fixture must keep.

The numbers in this module *are* the fixture, not tunable harness settings: a
changed athlete is a new fixture version, never an edit applied to an old sweep.
The run shapes are built with ``tests.builders`` so the coordinate maths and the
fixed start discipline are shared with the rest of the suite.

``EXPECTATIONS`` is the part that stops a fixture from rotting: the red-flag
scenario is only useful if it still has a sharp load increase and an active pain
episode, so the builder and the test suite both assert it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from app import coaching
from app.parsers import Activity, TrackPoint
from tests.builders import make_activity, make_points, speed_for_pace

SCENARIOS = ("healthy", "red_flags", "calibrating")

# Each run is (days before the block anchor, minutes, pace s/km, tag).
# The block anchor walks back one week at a time, so the last block ends today.
_HEALTHY_RUNS = (
    (0, 45, 360, "easy"),
    (2, 25, 245, "intervals"),
    (4, 25, 310, "tempo"),
    (5, 90, 360, "long"),
    (6, 55, 375, "easy"),
)

PROFILE = {
    "name": "Synthetic Athlete",
    "birth_date": "1992-04-18",
    "height_cm": 178,
    "sex": "unspecified",
}

EXPECTATIONS: dict[str, dict] = {
    "healthy": {
        "load_change_band": {"steady", "ramping_up"},
        "load_prev_7d_min": 0.0,
        "calibrating": False,
        "max_active_pain_episodes": 0,
        "intensity_easy_min_pct": 70.0,
        "intensity_sum_pct": 100.0,
        "race_distance_m": 10_000,
        "race_within_days": 365,
    },
    "red_flags": {
        "load_change_ratio_min": 1.5,
        "load_change_band": {"sharp_increase"},
        "week_on_week_min": 0.30,
        "active_pain_max_severity_within_days": 7,
        "race_distance_m": 10_000,
        "race_within_days": 12,
        "calibrating": False,
        "min_warn_red_flags": 1,
        "tsb_max": -20.0,
    },
    "calibrating": {
        "calibrating": True,
        "history_max_days": 42,
        "min_activities": 3,
    },
}

_RACE_GOAL = re.compile(r"Race: 10 km on (\d{4}-\d{2}-\d{2})")


@dataclass
class ScenarioData:
    """Everything the real snapshot builder and tool context need."""

    name: str
    as_of: date
    activities: list[Activity]
    rpe: dict[str, int]
    profile: dict
    weights: list[dict]
    shoes: list[dict]
    goals: list[dict]
    notes: dict[str, str]
    feedback: dict[str, dict]
    sessions: list[dict]
    nutrition: list[dict]
    supplements: list[dict]
    plans: list[dict] = field(default_factory=list)


def _at(day: date) -> datetime:
    return datetime.combine(day, time(8, 0, tzinfo=timezone.utc))


def _run(
    scenario: str,
    day: date,
    minutes: int,
    pace_s_per_km: float,
    tag: str,
) -> Activity:
    points = make_points(
        [(minutes * 60.0, speed_for_pace(pace_s_per_km))],
        start=_at(day),
        step_s=60.0,
    )
    return make_activity(
        points,
        activity_id=f"{scenario}-{day.isoformat()}-{tag}",
        name=f"{tag.replace('_', ' ').title()} {day.isoformat()}",
    )


def _weights(as_of: date) -> list[dict]:
    return [
        {
            "date": (as_of - timedelta(days=offset)).isoformat(),
            "weight_kg": round(71.4 - offset * 0.02, 1),
        }
        for offset in (0, 7, 14, 21, 28)
    ]


def _goal(as_of: date, metric: str, target: float, current: float, period: str):
    return {
        "id": 1,
        "period": period,
        "metric": metric,
        "target": target,
        "progress": {
            "current": current,
            "target": target,
            "percent": round(100.0 * current / target, 1),
            "period_start": (as_of - timedelta(days=6)).isoformat(),
            "period_end": as_of.isoformat(),
        },
    }


def _nutrition(as_of: date, days: int) -> list[dict]:
    rows = []
    for offset in range(days):
        rows.append(
            {
                "id": offset + 1,
                "date": (as_of - timedelta(days=offset)).isoformat(),
                "macros": {
                    "calories": 2400 + offset * 10,
                    "protein_g": 130,
                    "carbs_g": 290,
                    "fat_g": 75,
                },
                "steps": 9000 + offset * 250,
                "hydration_l": 2.4,
                "energy": 4,
                "appetite": 4,
                "fueling_before": offset % 2 == 0,
                "fueling_during": offset % 3 == 0,
                "fueling_after": True,
                "supplements_taken": [1],
            }
        )
    return rows


def _plan(
    activities: list[Activity],
    rpe: dict[str, int],
    as_of: date,
    *,
    name: str,
    start_offset_days: int,
    race_in_days: int,
) -> dict:
    data = coaching.generate_plan(
        activities,
        name=name,
        goal_distance_m=10_000,
        goal_date=(as_of + timedelta(days=race_in_days)).isoformat(),
        start_date=(as_of - timedelta(days=start_offset_days)).isoformat(),
    )
    fit = coaching.fitness_series(activities, rpe)["current"] or {}
    data["projection"] = coaching.project_plan(data, fit.get("ctl") or 0.0)
    return {
        "id": 1,
        "name": name,
        "goal_description": data["goal_description"],
        "weeks": data["weeks"],
        "data": data,
    }


def _healthy(as_of: date) -> ScenarioData:
    activities: list[Activity] = []
    for week in range(9):
        anchor = as_of - timedelta(days=7 * week)
        for offset, minutes, pace, tag in _HEALTHY_RUNS:
            activities.append(
                _run("healthy", anchor - timedelta(days=offset), minutes, pace, tag)
            )
    notes = {
        activities[0].id: "Felt smooth, legs fresh.",
        activities[2].id: "Tempo effort controlled on the flat loop.",
        activities[4].id: "Long run fuelled well, no niggles.",
    }
    sessions = [
        {
            "id": 1,
            "date": (as_of - timedelta(days=3)).isoformat(),
            "time": "18:00",
            "kind": "mobility",
            "title": "Hip mobility",
            "duration_min": 20,
            "rpe": 2,
            "status": "completed",
            "exercises": [
                {"name": "90/90", "sets": 2, "reps": 8, "duration_s": None},
                {"name": "Hip flexor stretch", "sets": 2, "duration_s": 45},
            ],
            "source": "manual",
        },
        {
            "id": 2,
            "date": (as_of - timedelta(days=7)).isoformat(),
            "time": "18:00",
            "kind": "strength",
            "title": "Lower body",
            "duration_min": 40,
            "rpe": 6,
            "status": "completed",
            "exercises": [
                {"name": "Hip thrust", "sets": 3, "reps": 10, "weight_kg": 60},
                {"name": "Calf raise", "sets": 3, "reps": 12, "weight_kg": 20},
            ],
            "source": "manual",
        },
    ]
    return ScenarioData(
        name="healthy",
        as_of=as_of,
        activities=activities,
        rpe={},
        profile=dict(PROFILE),
        weights=_weights(as_of),
        shoes=[
            {
                "id": 1,
                "name": "Daily trainer",
                "notes": "Road, easy and long runs",
                "threshold_km": 800,
                "retired": False,
                "distance_m": 412_000.0,
                "activities_count": 28,
            },
            {
                "id": 2,
                "name": "Tempo shoe",
                "notes": "Quality sessions",
                "threshold_km": 600,
                "retired": False,
                "distance_m": 186_000.0,
                "activities_count": 11,
            },
        ],
        goals=[_goal(as_of, "distance", 40_000.0, 32_000.0, "weekly")],
        notes=notes,
        feedback={},
        sessions=sessions,
        nutrition=_nutrition(as_of, 7),
        supplements=[
            {"id": 1, "name": "Vitamin D", "dose": "1000 IU", "frequency": "daily"}
        ],
        plans=[
            _plan(
                activities,
                {},
                as_of,
                name="10 km build",
                start_offset_days=21,
                race_in_days=35,
            )
        ],
    )


def _red_flags(as_of: date) -> ScenarioData:
    activities: list[Activity] = []
    rpe: dict[str, int] = {}
    for week in range(8):
        anchor = as_of - timedelta(days=7 * week)
        factor = 1.6 if week == 0 else 1.0
        for offset, minutes, pace, effort, tag in (
            (0, 60, 360, 2, "easy"),
            (2, 30, 245, 5, "intervals"),
            (4, 75, 360, 2, "easy"),
            (6, 90, 360, 2, "long"),
        ):
            activity = _run(
                "red_flags",
                anchor - timedelta(days=offset),
                int(minutes * factor),
                pace,
                tag,
            )
            activities.append(activity)
            rpe[activity.id] = effort

    # One obvious RPE/pace divergence, placed outside the chronic window so it
    # cannot move the load-change ratio this scenario exists to demonstrate.
    divergence = _run("red_flags", as_of - timedelta(days=40), 30, 420, "divergence")
    activities.append(divergence)
    rpe[divergence.id] = 7

    pain_runs = {
        (as_of - timedelta(days=4)).isoformat(): 4,
        (as_of - timedelta(days=2)).isoformat(): 6,
    }
    feedback: dict[str, dict] = {}
    for activity in activities:
        day = activity.start_time.date().isoformat()
        if day in pain_runs:
            feedback[activity.id] = {
                "session_type": "easy",
                "surface": "road",
                "completed": "full",
                "pain": True,
                "pain_location": "knee",
                "pain_side": "right",
                "pain_severity": pain_runs[day],
                "pain_timing": "during",
                "pain_trend": "worse",
                "readiness": 3,
                "legs": 2,
            }
            pain_runs.pop(day)

    sessions = [
        {
            "id": 1,
            "date": (as_of - timedelta(days=5)).isoformat(),
            "time": "18:00",
            "kind": "strength",
            "title": "Lower body",
            "duration_min": 50,
            "rpe": 8,
            "status": "completed",
            "exercises": [
                {"name": "Leg press", "sets": 3, "reps": 10, "weight_kg": 90},
                {"name": "Bulgarian split squat", "sets": 3, "reps": 8},
            ],
            "source": "manual",
        },
        {
            "id": 2,
            "date": (as_of - timedelta(days=9)).isoformat(),
            "time": "18:00",
            "kind": "mobility",
            "title": "Mobility",
            "duration_min": 20,
            "rpe": 2,
            "status": "completed",
            "exercises": [{"name": "Hip mobility", "sets": 2, "duration_s": 60}],
            "source": "manual",
        },
    ]
    pain_note_id = next(
        (
            activity.id
            for activity in activities
            if (as_of - activity.start_time.date()).days == 4
        ),
        None,
    )
    return ScenarioData(
        name="red_flags",
        as_of=as_of,
        activities=activities,
        rpe=rpe,
        profile=dict(PROFILE),
        weights=_weights(as_of),
        shoes=[
            {
                "id": 1,
                "name": "Race shoe",
                "notes": "Carbon plate, race day only",
                "threshold_km": 400,
                "retired": False,
                "distance_m": 96_000.0,
                "activities_count": 6,
            }
        ],
        goals=[_goal(as_of, "distance", 150_000.0, 84_000.0, "monthly")],
        notes=(
            {pain_note_id: "Easy loop, knee sore afterwards."} if pain_note_id else {}
        ),
        feedback=feedback,
        sessions=sessions,
        nutrition=_nutrition(as_of, 3),
        supplements=[],
        plans=[
            _plan(
                activities,
                rpe,
                as_of,
                name="10 km race build",
                start_offset_days=42,
                race_in_days=10,
            )
        ],
    )


def _calibrating(as_of: date) -> ScenarioData:
    activities = [
        _run("calibrating", as_of - timedelta(days=offset), minutes, pace, tag)
        for offset, minutes, pace, tag in (
            (18, 30, 420, "recovery"),
            (14, 40, 360, "easy"),
            (9, 35, 360, "easy"),
            (4, 50, 360, "easy"),
            (1, 25, 310, "tempo"),
        )
    ]
    return ScenarioData(
        name="calibrating",
        as_of=as_of,
        activities=activities,
        rpe={},
        profile=dict(PROFILE),
        weights=_weights(as_of)[:2],
        shoes=[
            {
                "id": 1,
                "name": "Everyday trainer",
                "notes": "New pair",
                "threshold_km": 800,
                "retired": False,
                "distance_m": 64_000.0,
                "activities_count": 5,
            }
        ],
        goals=[_goal(as_of, "time", 10_800.0, 9_000.0, "weekly")],
        notes={activities[-1].id: "First tempo since starting back."},
        feedback={},
        sessions=[],
        nutrition=[],
        supplements=[],
        plans=[],
    )


_BUILDERS = {
    "healthy": _healthy,
    "red_flags": _red_flags,
    "calibrating": _calibrating,
}


def build(name: str, as_of: date | None = None) -> ScenarioData:
    """Build one synthetic athlete frozen on ``as_of`` (today by default)."""
    if name not in _BUILDERS:
        raise ValueError(f"Unknown scenario: {name!r}")
    return _BUILDERS[name](as_of or date.today())


def build_snapshot(data: ScenarioData) -> dict:
    """Call the production snapshot builder with the scenario's inputs."""
    return coaching.build_snapshot(
        data.activities,
        data.rpe,
        data.profile,
        data.weights,
        data.shoes,
        data.goals,
        data.notes,
        feedback_map=data.feedback,
        sessions=data.sessions,
        nutrition=data.nutrition,
        supplements=data.supplements,
    )


def serialize_tool_context(data: ScenarioData) -> dict:
    """Serialise the tool context the way the frozen fixture stores it."""
    return {
        "activities": [
            {
                "id": activity.id,
                "name": activity.name,
                "type": activity.activity_type,
                "start_time": activity.start_time.isoformat(),
                "points": [
                    [
                        round(point.lat, 7),
                        round(point.lon, 7),
                        point.time.isoformat(),
                        round(point.speed, 3),
                    ]
                    for point in activity.points
                ],
            }
            for activity in data.activities
        ],
        "rpe": data.rpe,
        "feedback": data.feedback,
        "notes": data.notes,
        "sessions": data.sessions,
        "weights": data.weights,
        "nutrition": data.nutrition,
        "shoes": data.shoes,
        "plans": data.plans,
        "verdicts": {},
        "today": data.as_of.isoformat(),
    }


def deserialize_tool_context(payload: dict) -> dict:
    """Rebuild ``Activity`` objects from the frozen JSON.

    ``coach_tools`` consumes the production model, not JSON. Reconstructing the
    points here is what lets the benchmark call the real dispatcher instead of a
    parallel implementation that would drift.
    """
    activities = []
    for row in payload.get("activities") or []:
        points = [
            TrackPoint(
                lat=lat,
                lon=lon,
                time=datetime.fromisoformat(timestamp),
                speed=speed,
            )
            for lat, lon, timestamp, speed in row.get("points") or []
        ]
        activities.append(
            Activity(
                id=row["id"],
                filename=f"{row['id']}.kmz",
                name=row.get("name") or row["id"],
                description=None,
                activity_type=row.get("type") or "running",
                activity_type_raw=row.get("type") or "running",
                points=points,
                segments=[points],
                markers=[],
            )
        )
    return {**payload, "activities": activities}


def _active_pain_episodes(snapshot: dict) -> list[dict]:
    return [
        episode
        for episode in (snapshot.get("injuries") or {}).get("episodes") or []
        if episode.get("active")
    ]


def _race_goal(tool_context: dict) -> date | None:
    for plan in tool_context.get("plans") or []:
        description = plan.get("goal_description") or ""
        match = _RACE_GOAL.search(description)
        if match:
            return date.fromisoformat(match.group(1))
    return None


def check_expectations(name: str, snapshot: dict, tool_context: dict) -> list[str]:
    """Return the declared properties this fixture no longer satisfies."""
    expected = EXPECTATIONS.get(name)
    if expected is None:
        return [f"no expectations declared for {name!r}"]

    failures: list[str] = []
    load_change = snapshot.get("load_change") or {}
    load = snapshot.get("load") or {}
    fitness = snapshot.get("fitness") or {}
    as_of = date.fromisoformat(tool_context["today"])

    if "load_change_band" in expected:
        if load_change.get("band") not in expected["load_change_band"]:
            failures.append(
                f"load_change.band is {load_change.get('band')!r}, "
                f"expected one of {sorted(expected['load_change_band'])}"
            )
    if "load_prev_7d_min" in expected:
        if (load.get("prev_7d") or 0) <= expected["load_prev_7d_min"]:
            failures.append("load.prev_7d is not positive")
    if "calibrating" in expected:
        if fitness.get("calibrating") is not expected["calibrating"]:
            failures.append(
                f"fitness.calibrating is {fitness.get('calibrating')!r}, "
                f"expected {expected['calibrating']!r}"
            )

    active = _active_pain_episodes(snapshot)
    if "max_active_pain_episodes" in expected:
        if len(active) > expected["max_active_pain_episodes"]:
            failures.append(f"{len(active)} active pain episode(s), expected none")

    intensity = snapshot.get("intensity_28d") or {}
    if "intensity_easy_min_pct" in expected:
        easy = intensity.get("easy_pct")
        if easy is None or easy < expected["intensity_easy_min_pct"]:
            failures.append(f"easy share is {easy!r}, expected >= 70%")
    if "intensity_sum_pct" in expected:
        groups = [
            intensity.get("easy_pct"),
            intensity.get("moderate_pct"),
            intensity.get("hard_pct"),
        ]
        if any(value is None for value in groups):
            failures.append("an intensity group is missing")
        elif abs(sum(groups) - expected["intensity_sum_pct"]) > 1.0:
            failures.append(f"intensity groups sum to {sum(groups):.1f}, expected ~100")

    if "load_change_ratio_min" in expected:
        ratio = load_change.get("ratio")
        if ratio is None or ratio <= expected["load_change_ratio_min"]:
            failures.append(f"load_change.ratio is {ratio!r}, expected > 1.5")
    if "week_on_week_min" in expected:
        previous = load.get("prev_7d") or 0
        if previous <= 0:
            failures.append("load.prev_7d is zero, cannot compute week-on-week")
        elif (load.get("last_7d") or 0) / previous - 1 <= expected["week_on_week_min"]:
            failures.append("week-on-week change is not above 30%")
    if "active_pain_max_severity_within_days" in expected:
        window = expected["active_pain_max_severity_within_days"]
        recent = [
            episode
            for episode in active
            if (as_of - date.fromisoformat(episode["last_date"])).days <= window
        ]
        if not recent:
            failures.append("no active pain episode reported in the last 7 days")
        elif max((episode.get("max_severity") or 0) for episode in recent) <= 0:
            failures.append("active pain episode has no severity")
    if "race_distance_m" in expected:
        race_day = _race_goal(tool_context)
        if race_day is None:
            failures.append("no 10 km race goal in the tool context")
        else:
            distance = (race_day - as_of).days
            if distance < 0 or distance > expected["race_within_days"]:
                failures.append(f"race goal is {distance} days away")
    if "min_warn_red_flags" in expected:
        warns = [
            flag
            for flag in snapshot.get("red_flags") or []
            if flag.get("level") == "warn"
        ]
        if len(warns) < expected["min_warn_red_flags"]:
            failures.append("no warn-level red flag in the snapshot")
    if "tsb_max" in expected:
        tsb = fitness.get("tsb")
        if tsb is None or tsb >= expected["tsb_max"]:
            failures.append(f"fitness.tsb is {tsb!r}, expected below -20")

    if "history_max_days" in expected:
        days = [
            activity.start_time
            for activity in tool_context.get("activities") or []
            if activity.start_time
        ]
        if days:
            history = (as_of - min(days).date()).days
            if history >= expected["history_max_days"]:
                failures.append(f"history is {history} days, expected < 42")
        else:
            failures.append("no activities in the tool context")
    if "min_activities" in expected:
        count = len(tool_context.get("activities") or [])
        if count < expected["min_activities"]:
            failures.append(f"{count} activities, expected at least 3")

    return failures
