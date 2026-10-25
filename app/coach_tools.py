"""Read-only tools the coach can call during a conversation.

The snapshot gives the model a fixed summary. These tools answer the follow-up
questions a summary cannot: *which* runs, *which* session, *which* effort, with
what conditions.

Rules that hold for every tool here:

- **Read-only.** Nothing writes.
- **Bounded.** At most 50 rows, and every list is capped, so a chatty model
  cannot blow the context window.
- **Aggregates only.** No GPS coordinates, no full notes. The athlete's home
  address is not a fact the coach needs.

The dispatcher takes a context dict instead of reaching into the app, so it is
pure and testable without FastAPI, a database or a network.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from . import analysis, coaching
from .activity import compute_stats
from .config import INTENSITY_GROUPS
from .parsers import Activity

MAX_ROWS = 50


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _date_arg(arguments: dict, key: str) -> Optional[date]:
    """Read a date argument, rejecting a malformed one instead of ignoring it."""
    raw = arguments.get(key)
    if not raw:
        return None
    parsed = _parse_date(raw)
    if parsed is None:
        raise ValueError(f"{key} must be YYYY-MM-DD (received {raw!r})")
    return parsed


def _number(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _activity_date(activity: Activity) -> Optional[date]:
    return activity.start_time.date() if activity.start_time else None


def _pace(stats: dict) -> Optional[float]:
    pace = stats.get("avg_pace_s_per_km") or 0
    return round(pace, 1) if pace else None


def _row(activity: Activity, rpe: Optional[int]) -> dict:
    stats = compute_stats(activity)
    return {
        "activity_id": activity.id,
        "date": _activity_date(activity).isoformat(),
        "name": activity.name,
        "type": activity.activity_type,
        "distance_km": round(stats["distance_m"] / 1000.0, 2),
        "moving_min": round(stats["moving_time_s"] / 60.0, 1),
        "pace_s_per_km": _pace(stats),
        "elevation_gain_m": round(stats["elevation_gain_m"]),
        "rpe": rpe,
    }


# ---------------------------------------------------------------------------
# search_activities
# ---------------------------------------------------------------------------
def search_activities(context: dict, arguments: dict) -> dict:
    """Filter the athlete's runs by date, distance and type."""
    activities = context.get("activities") or []
    rpe_map = context.get("rpe") or {}
    from_date = _date_arg(arguments, "from_date")
    to_date = _date_arg(arguments, "to_date")
    min_km = _number(arguments.get("min_distance_km"))
    max_km = _number(arguments.get("max_distance_km"))
    activity_type = (arguments.get("activity_type") or "").strip().lower()
    conditions = (arguments.get("conditions") or "").strip().lower()
    feedback = context.get("feedback") or {}
    limit = int(_number(arguments.get("limit")) or 10)
    limit = max(1, min(limit, MAX_ROWS))

    rows = []
    for activity in activities:
        day = _activity_date(activity)
        if day is None:
            continue
        if from_date and day < from_date:
            continue
        if to_date and day > to_date:
            continue
        if activity_type and activity.activity_type != activity_type:
            continue
        if conditions:
            reported = (feedback.get(activity.id) or {}).get("conditions") or ""
            if reported != conditions:
                continue
        stats = compute_stats(activity)
        distance_km = stats["distance_m"] / 1000.0
        if min_km is not None and distance_km < min_km:
            continue
        if max_km is not None and distance_km > max_km:
            continue
        rows.append(_row(activity, rpe_map.get(activity.id)))

    rows.sort(key=lambda row: row["date"], reverse=True)
    return {
        "matched": len(rows),
        "returned": min(len(rows), limit),
        "activities": rows[:limit],
    }


# ---------------------------------------------------------------------------
# get_activity
# ---------------------------------------------------------------------------
def get_activity(context: dict, arguments: dict) -> dict:
    """Detail for one run: splits, feedback, conditions, RPE."""
    activity_id = str(arguments.get("activity_id") or "").strip()
    activity = next(
        (a for a in context.get("activities") or [] if a.id == activity_id), None
    )
    if activity is None:
        return {"error": f"No activity with id {activity_id!r}"}

    stats = compute_stats(activity)
    feedback = (context.get("feedback") or {}).get(activity_id) or {}
    splits = analysis.compute_splits(activity.points)[:12]

    return {
        "activity_id": activity.id,
        "date": _activity_date(activity).isoformat()
        if _activity_date(activity)
        else None,
        "name": activity.name,
        "type": activity.activity_type,
        "distance_km": round(stats["distance_m"] / 1000.0, 2),
        "moving_min": round(stats["moving_time_s"] / 60.0, 1),
        "pace_s_per_km": _pace(stats),
        "elevation_gain_m": round(stats["elevation_gain_m"]),
        "rpe": (context.get("rpe") or {}).get(activity_id),
        "conditions": feedback.get("conditions") or None,
        "surface": feedback.get("surface") or None,
        "readiness": feedback.get("readiness"),
        "legs": feedback.get("legs"),
        "pain": {
            "reported": bool(feedback.get("pain")),
            "location": feedback.get("pain_location") or None,
            "side": feedback.get("pain_side") or None,
            "severity": feedback.get("pain_severity"),
            "timing": feedback.get("pain_timing") or None,
            "trend": feedback.get("pain_trend") or None,
        },
        "splits": [
            {
                "km": split.get("km"),
                "pace_s_per_km": split.get("pace_s_per_km"),
                "elevation_gain_m": split.get("elevation_gain_m"),
            }
            for split in splits
        ],
        "note": (context.get("notes") or {}).get(activity_id, "")[:300] or None,
    }


# ---------------------------------------------------------------------------
# best_efforts
# ---------------------------------------------------------------------------
def best_efforts(context: dict, arguments: dict) -> dict:
    """Best times over the reference distances, optionally for one distance."""
    wanted_km = _number(arguments.get("distance_km"))
    achievements: list[dict] = []
    for activity in context.get("activities") or []:
        day = _activity_date(activity)
        if day is None:
            continue
        for effort in analysis.compute_best_efforts(activity):
            achievements.append(
                {
                    "distance_km": round(effort["distance_m"] / 1000.0, 3),
                    "time_s": round(effort["time_s"], 1),
                    "pace_s_per_km": effort["pace_s_per_km"],
                    "date": day.isoformat(),
                    "activity_id": activity.id,
                }
            )

    if not achievements:
        return {"distance_km": wanted_km, "efforts": [], "note": "No best efforts yet"}

    if wanted_km is not None:
        candidates = [
            item
            for item in achievements
            if abs(item["distance_km"] - wanted_km) <= max(0.02, wanted_km * 0.02)
        ]
        candidates.sort(key=lambda item: item["time_s"])
        return {
            "distance_km": wanted_km,
            "efforts": candidates[:5],
            "count": len(candidates),
        }

    best: dict[float, dict] = {}
    for item in achievements:
        current = best.get(item["distance_km"])
        if current is None or item["time_s"] < current["time_s"]:
            best[item["distance_km"]] = item
    ordered = [best[key] for key in sorted(best)]
    return {"distance_km": None, "efforts": ordered, "count": len(ordered)}


# ---------------------------------------------------------------------------
# get_sessions
# ---------------------------------------------------------------------------
def get_sessions(context: dict, arguments: dict) -> dict:
    """Strength, mobility and cross-training sessions with their exercises."""
    from_date = _date_arg(arguments, "from_date")
    to_date = _date_arg(arguments, "to_date")
    kind = (arguments.get("kind") or "").strip().lower()
    limit = int(_number(arguments.get("limit")) or 10)
    limit = max(1, min(limit, MAX_ROWS))

    rows = []
    for session in context.get("sessions") or []:
        day = _parse_date(session.get("date"))
        if day is None:
            continue
        if from_date and day < from_date:
            continue
        if to_date and day > to_date:
            continue
        if kind and session.get("kind") != kind:
            continue
        rows.append(
            {
                "date": session.get("date"),
                "kind": session.get("kind"),
                "title": session.get("title") or None,
                "duration_min": session.get("duration_min"),
                "rpe": session.get("rpe"),
                "status": session.get("status"),
                "exercises": [
                    {
                        "name": exercise.get("name"),
                        "sets": exercise.get("sets"),
                        "reps": exercise.get("reps"),
                        "weight_kg": exercise.get("weight_kg"),
                        "duration_s": exercise.get("duration_s"),
                    }
                    for exercise in session.get("exercises") or []
                ],
            }
        )

    rows.sort(key=lambda row: row["date"], reverse=True)
    return {
        "matched": len(rows),
        "returned": min(len(rows), limit),
        "sessions": rows[:limit],
    }


# ---------------------------------------------------------------------------
# get_load_series
# ---------------------------------------------------------------------------
def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def get_load_series(context: dict, arguments: dict) -> dict:
    """Daily or weekly training load with the chronic and acute averages."""
    days = int(_number(arguments.get("days")) or 84)
    days = max(7, min(days, 365))
    bucket = (arguments.get("bucket") or "week").strip().lower()
    if bucket not in ("day", "week"):
        bucket = "week"

    activities = context.get("activities") or []
    rpe_map = context.get("rpe") or {}
    load_days = coaching.full_load_series(activities, rpe_map)
    if not load_days:
        return {"bucket": bucket, "points": []}
    # The load series carries the activity count; the fitness series carries
    # the moving averages. Merge them by date.
    fitness = {
        day["date"]: day for day in coaching.fitness_series(activities, rpe_map)["days"]
    }
    series = [
        {
            "date": day["date"],
            "load": day["load"],
            "activities": day.get("activities", 0),
            "ctl": fitness.get(day["date"], {}).get("ctl"),
            "atl": fitness.get(day["date"], {}).get("atl"),
        }
        for day in load_days
    ][-days:]

    if bucket == "day":
        points = [
            {
                "date": day["date"],
                "load": day["load"],
                "activities": day.get("activities", 0),
                "ctl": day.get("ctl"),
                "atl": day.get("atl"),
            }
            for day in series
        ]
    else:
        grouped: dict[str, dict] = {}
        for day in series:
            week = _week_start(date.fromisoformat(day["date"])).isoformat()
            entry = grouped.setdefault(
                week, {"week_start": week, "load": 0.0, "activities": 0, "days": 0}
            )
            entry["load"] += day.get("load") or 0
            entry["activities"] += day.get("activities") or 0
            entry["days"] += 1
            entry["ctl"] = day.get("ctl")
            entry["atl"] = day.get("atl")
        points = [
            {
                "week_start": entry["week_start"],
                "load": round(entry["load"], 1),
                "activities": entry["activities"],
                "days": entry["days"],
                "ctl_end": entry.get("ctl"),
                "atl_end": entry.get("atl"),
            }
            for _, entry in sorted(grouped.items())
        ]

    loads = [point["load"] for point in points]
    return {
        "bucket": bucket,
        "from_date": series[0]["date"],
        "to_date": series[-1]["date"],
        "note": "The series starts at the first recorded activity; earlier days have no data.",
        "points": points,
        "total_load": round(sum(loads), 1),
        "highest": max(points, key=lambda point: point["load"]) if points else None,
    }


# ---------------------------------------------------------------------------
# get_weights
# ---------------------------------------------------------------------------
def get_weights(context: dict, arguments: dict) -> dict:
    """Weight history, oldest first, with the trend per week."""
    limit = int(_number(arguments.get("limit")) or 30)
    limit = max(2, min(limit, 120))

    rows = sorted(
        (row for row in context.get("weights") or [] if row.get("weight_kg")),
        key=lambda row: row.get("date", ""),
    )
    if not rows:
        return {"points": [], "trend_kg_per_week": None, "note": "No weight logged"}
    rows = rows[-limit:]

    first, last = rows[0], rows[-1]
    trend = None
    first_day, last_day = _parse_date(first["date"]), _parse_date(last["date"])
    if first_day and last_day and (last_day - first_day).days >= 7:
        weeks = (last_day - first_day).days / 7.0
        trend = round((last["weight_kg"] - first["weight_kg"]) / weeks, 2)

    return {
        "points": [
            {"date": row["date"], "weight_kg": round(float(row["weight_kg"]), 1)}
            for row in rows
        ],
        "first_kg": round(float(first["weight_kg"]), 1),
        "last_kg": round(float(last["weight_kg"]), 1),
        "change_kg": round(float(last["weight_kg"]) - float(first["weight_kg"]), 1),
        "trend_kg_per_week": trend,
        "window_days": (last_day - first_day).days if first_day and last_day else None,
    }


# ---------------------------------------------------------------------------
# get_nutrition
# ---------------------------------------------------------------------------
def get_nutrition(context: dict, arguments: dict) -> dict:
    """Daily nutrition, steps and check-in values, newest first."""
    from_date = _date_arg(arguments, "from_date")
    to_date = _date_arg(arguments, "to_date")
    limit = int(_number(arguments.get("limit")) or 14)
    limit = max(1, min(limit, 60))

    rows = []
    for row in context.get("nutrition") or []:
        day = _parse_date(row.get("date"))
        if day is None:
            continue
        if from_date and day < from_date:
            continue
        if to_date and day > to_date:
            continue
        macros = row.get("macros") or {}
        rows.append(
            {
                "date": row["date"],
                "calories": macros.get("calories"),
                "protein_g": macros.get("protein_g"),
                "carbs_g": macros.get("carbs_g"),
                "fat_g": macros.get("fat_g"),
                "steps": row.get("steps"),
                "hydration_l": row.get("hydration_l"),
                "energy_1_5": row.get("energy"),
                "appetite_1_5": row.get("appetite"),
                "fueling": {
                    "before": bool(row.get("fueling_before")),
                    "during": bool(row.get("fueling_during")),
                    "after": bool(row.get("fueling_after")),
                },
            }
        )

    rows.sort(key=lambda item: item["date"], reverse=True)

    def average(field):
        values = [
            row[field] for row in rows if isinstance(row.get(field), (int, float))
        ]
        return round(sum(values) / len(values), 1) if values else None

    return {
        "matched": len(rows),
        "returned": min(len(rows), limit),
        "days": rows[:limit],
        "average_calories": average("calories"),
        "average_protein_g": average("protein_g"),
        "average_steps": average("steps"),
    }


# ---------------------------------------------------------------------------
# compare_periods
# ---------------------------------------------------------------------------
def _intensity_percentages(activities: list) -> dict:
    totals = {name: 0.0 for name in INTENSITY_GROUPS}
    for activity in activities:
        zones = analysis.compute_pace_zones(activity.points, use_gap=True)["zones"]
        for name, config in INTENSITY_GROUPS.items():
            for index in config["zones"]:
                totals[name] += zones[index]["time_s"]
    overall = sum(totals.values())
    if overall <= 0:
        return {name: None for name in totals}
    return {name: round(100.0 * value / overall, 1) for name, value in totals.items()}


def _period_summary(context: dict, start: date, end: date) -> dict:
    activities = [
        activity
        for activity in context.get("activities") or []
        if _activity_date(activity) and start <= _activity_date(activity) <= end
    ]
    rpe_map = context.get("rpe") or {}
    distance = moving = elevation = load = 0.0
    for activity in activities:
        stats = compute_stats(activity)
        distance += stats["distance_m"]
        moving += stats["moving_time_s"]
        elevation += stats["elevation_gain_m"]
        load += coaching.activity_load(activity, rpe_map.get(activity.id))["load"]

    sessions = [
        session
        for session in context.get("sessions") or []
        if (day := _parse_date(session.get("date"))) and start <= day <= end
    ]
    kinds: dict[str, int] = {}
    for session in sessions:
        kind = session.get("kind") or "other"
        kinds[kind] = kinds.get(kind, 0) + 1

    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "activities": len(activities),
        "distance_km": round(distance / 1000.0, 1),
        "moving_min": round(moving / 60.0, 1),
        "elevation_gain_m": round(elevation),
        "average_pace_s_per_km": round(moving / (distance / 1000.0), 1)
        if distance
        else None,
        "total_load": round(load, 1),
        "intensity_pct": _intensity_percentages(activities),
        "sessions": {"total": len(sessions), "by_kind": kinds},
    }


def compare_periods(context: dict, arguments: dict) -> dict:
    """Two date ranges side by side, with the difference between them."""
    start_a = _date_arg(arguments, "from_date")
    end_a = _date_arg(arguments, "to_date")
    start_b = _date_arg(arguments, "compare_from_date")
    end_b = _date_arg(arguments, "compare_to_date")

    if start_a and end_a and start_b and end_b:
        pass
    else:
        days = int(_number(arguments.get("days")) or 28)
        days = max(7, min(days, 365))
        today = date.today()
        end_b = today - timedelta(days=days)
        start_b = end_b - timedelta(days=days - 1)
        end_a = today
        start_a = end_a - timedelta(days=days - 1)

    if start_a > end_a or start_b > end_b:
        return {"error": "A period ends before it starts"}

    first = _period_summary(context, start_a, end_a)
    second = _period_summary(context, start_b, end_b)

    def delta(key):
        return round(first[key] - second[key], 1)

    return {
        "current": first,
        "comparison": second,
        "delta": {
            "activities": first["activities"] - second["activities"],
            "distance_km": delta("distance_km"),
            "moving_min": delta("moving_min"),
            "total_load": delta("total_load"),
            "easy_pct": round(
                (first["intensity_pct"]["easy"] or 0)
                - (second["intensity_pct"]["easy"] or 0),
                1,
            ),
        },
        "note": "The first period is the current one; the delta is current minus comparison.",
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_activities",
            "description": (
                "List the athlete's runs, newest first, filtered by date range, "
                "distance or activity type. Use it when the question names a "
                "period or a kind of run the snapshot summary does not break down."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "to_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "min_distance_km": {"type": "number"},
                    "max_distance_km": {"type": "number"},
                    "activity_type": {
                        "type": "string",
                        "enum": [
                            "running",
                            "trail_running",
                            "street_running",
                            "track_running",
                        ],
                    },
                    "conditions": {
                        "type": "string",
                        "enum": ["cool", "temperate", "warm", "hot", "humid"],
                        "description": "Only runs where this was recorded",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ROWS},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_activity",
            "description": (
                "Full detail for one run: pace, elevation, kilometre splits, the "
                "post-run check-in (pain, readiness, conditions) and the note."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "activity_id": {
                        "type": "string",
                        "description": "The activity_id returned by search_activities",
                    }
                },
                "required": ["activity_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "best_efforts",
            "description": (
                "Best times over the reference distances, or the fastest efforts "
                "at one distance with their dates, to answer whether the athlete "
                "is improving."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "distance_km": {
                        "type": "number",
                        "description": "e.g. 5 for 5 km; omit for all distances",
                    }
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sessions",
            "description": (
                "Strength, mobility and cross-training sessions with the "
                "exercises recorded in each. Use it when pain or fatigue might "
                "relate to specific work."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "to_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "kind": {
                        "type": "string",
                        "enum": [
                            "strength",
                            "mobility",
                            "cross",
                            "rest",
                            "physio",
                            "other",
                        ],
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ROWS},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_load_series",
            "description": (
                "Training load over time, daily or weekly, with the chronic (CTL) "
                "and acute (ATL) averages. Use it for trend questions the snapshot "
                "summary cannot answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "minimum": 7, "maximum": 365},
                    "bucket": {"type": "string", "enum": ["day", "week"]},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weights",
            "description": (
                "Weight history, oldest first, with the total change and the trend "
                "per week."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 2, "maximum": 120},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_nutrition",
            "description": (
                "Daily nutrition: macros, steps, hydration, energy and appetite "
                "ratings, fueling flags. Newest first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "to_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 60},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_periods",
            "description": (
                "Two date ranges side by side: volume, load, pace, intensity "
                "distribution and sessions. With no ranges, compares the last N "
                "days with the N before."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from_date": {
                        "type": "string",
                        "description": "current period start",
                    },
                    "to_date": {"type": "string", "description": "current period end"},
                    "compare_from_date": {"type": "string"},
                    "compare_to_date": {"type": "string"},
                    "days": {
                        "type": "integer",
                        "minimum": 7,
                        "maximum": 365,
                        "description": "used only when no ranges are given",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
]

_HANDLERS = {
    "search_activities": search_activities,
    "get_load_series": get_load_series,
    "get_weights": get_weights,
    "get_nutrition": get_nutrition,
    "compare_periods": compare_periods,
    "get_activity": get_activity,
    "best_efforts": best_efforts,
    "get_sessions": get_sessions,
}


def dispatch(name: str, arguments: dict, context: dict) -> dict:
    """Run one tool call. Never raises: errors are returned for the model."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return handler(context, arguments or {})
    except Exception as exc:  # a bad tool call must not kill the conversation
        return {"error": f"{name} failed: {exc}"}
