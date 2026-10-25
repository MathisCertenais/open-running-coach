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

from datetime import date, datetime
from typing import Optional

from . import analysis
from .activity import compute_stats
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
]

_HANDLERS = {
    "search_activities": search_activities,
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
