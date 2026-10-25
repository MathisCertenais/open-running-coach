"""FastAPI entry point — exposes the running dashboard and its analyses."""

from __future__ import annotations

import hashlib
import logging
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import activity as activity_mod
from . import analysis, coach_llm, coaching, injuries, pacing
from . import connectors as connectors_mod
from . import exercises as exercises_mod
from . import report as report_mod
from . import uploads as uploads_mod
from .config import (
    DATA_DIR,
    DATA_NUTRITION_DIR,
    DATA_RUNNING_DIR,
    DATA_WATCH_SECONDS,
    DATA_WORKOUT_DIR,
    DB_PATH,
    FEEDBACK_COMPLETION,
    FEEDBACK_CONDITIONS,
    FEEDBACK_PAIN_LOCATIONS,
    FEEDBACK_PAIN_SIDES,
    FEEDBACK_PAIN_TIMINGS,
    FEEDBACK_PAIN_TRENDS,
    FEEDBACK_SESSION_TYPES,
    FEEDBACK_SURFACES,
    NUTRITION_ENERGY_MAX,
    NUTRITION_ENERGY_MIN,
    NUTRITION_HYDRATION_MAX_L,
    PLAN_DEFAULT_SESSIONS,
    SESSION_BODY_AREAS,
    SESSION_KINDS,
    SESSION_STATUS,
    STATIC_DIR,
    SUPPLEMENT_FREQUENCIES,
    UPLOAD_MAX_BYTES,
)
from .parsers import SUPPORTED_EXTENSIONS, Activity, parse_file
from .store import Store

logger = logging.getLogger("coach")


def _watch_data_folder() -> None:
    """Rescan in the background when files appear in data/.

    Makes an auto-exporting recorder (OpenTracks can export after every
    recording) land in the app without anyone pressing reload.
    """
    while True:
        time.sleep(DATA_WATCH_SECONDS)
        try:
            with _lock:
                if _signature != _data_signature():
                    _rescan()
                    logger.info("data folder changed: rescan complete")
        except Exception:  # pragma: no cover - a watcher must never die
            logger.exception("data watcher failed; retrying next tick")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if DATA_WATCH_SECONDS > 0:
        thread = threading.Thread(
            target=_watch_data_folder, name="data-watcher", daemon=True
        )
        thread.start()
    yield


app = FastAPI(title="Coach Running", version="0.3.0", lifespan=lifespan)

store = Store(DB_PATH)

# Make sure the data folders exist for non-technical users.
for _data_dir in (DATA_RUNNING_DIR, DATA_WORKOUT_DIR, DATA_NUTRITION_DIR):
    _data_dir.mkdir(parents=True, exist_ok=True)

# In-memory cache of parsed activities, guarded by a lock.
_lock = threading.Lock()
_activities: dict[str, Activity] = {}
_signature: Optional[tuple] = None


def _iter_running_files() -> list[Path]:
    """Running files from data/running/ (and the data/ root for compatibility)."""
    files = []
    for directory in (DATA_RUNNING_DIR, DATA_DIR):
        if not directory.exists():
            continue
        for ext in SUPPORTED_EXTENSIONS:
            files.extend(directory.glob("*" + ext))
    return sorted(
        {p.resolve() for p in files if p.is_file()},
        key=lambda p: (p.parent.name, p.name),
    )


def _data_signature() -> tuple:
    """Signature of all data folders to detect file changes."""
    items = []
    for path in _iter_running_files():
        items.append((str(path), path.stat().st_mtime_ns))
    for directory in (DATA_NUTRITION_DIR, DATA_WORKOUT_DIR):
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix.lower() in (".zip", ".csv", ".json"):
                items.append((str(path), path.stat().st_mtime_ns))
    return tuple(sorted(items))


def _fingerprint(act: Activity) -> tuple:
    """Fingerprint used to dedupe the same run imported from multiple sources.

    Keyed on the first/last GPS timestamps (points with coordinates — stable
    across formats) plus a coarse distance bucket. Moving time and the raw
    start/end (which can include no-coordinate markers) are intentionally
    avoided.
    """
    stats = activity_mod.compute_stats(act)
    times = [
        p.time
        for p in act.points
        if p.lat is not None and p.lon is not None and p.time is not None
    ]

    def stamp(t):
        return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") if t else None

    return (
        stamp(times[0]) if times else None,
        stamp(times[-1]) if times else None,
        round(stats["distance_m"] / 200.0),  # ~200 m buckets
    )


def _quality(act: Activity) -> int:
    """Richness score used to keep the best copy of a duplicated run."""
    score = len(act.points)
    score += len(act.segments) * 1000
    if any(p.hr is not None for p in act.points):
        score += 500
    if any(p.cadence is not None for p in act.points):
        score += 200
    return score


def _rescan() -> None:
    """(Re)parse running files and import external nutrition/workout exports."""
    global _activities, _signature
    parsed: dict[str, Activity] = {}

    acts: list[Activity] = []
    for path in _iter_running_files():
        act = parse_file(path)
        if act is not None and act.points:
            acts.append(act)

    # Dedupe by fingerprint, keeping the richest copy of each run.
    best: dict[tuple, Activity] = {}
    for act in acts:
        key = _fingerprint(act)
        prev = best.get(key)
        if prev is None or _quality(act) > _quality(prev):
            best[key] = act

    for act in best.values():
        parsed[act.id] = act
    _activities = parsed

    # Import external domains (only new/changed files are processed).
    connectors_mod.import_nutrition_dir(store, DATA_NUTRITION_DIR)
    connectors_mod.import_workout_dir(store, DATA_WORKOUT_DIR)

    _apply_auto_shoe(parsed)

    _signature = _data_signature()


def _apply_auto_shoe(activities: dict[str, Activity]) -> int:
    """Assign the default shoe to activities that have none.

    Only runs when the athlete enabled it, so the app never quietly attributes
    mileage to a pair they did not choose. Returns how many were assigned.
    """
    profile = store.get_profile()
    if profile.get("auto_assign_shoe") != "1":
        return 0
    raw = profile.get("default_shoe_id") or ""
    if not raw.isdigit():
        return 0
    shoe_id = int(raw)
    if not any(shoe["id"] == shoe_id for shoe in store.list_shoes()):
        return 0

    assigned = store.activity_shoe_map()
    count = 0
    for activity in activities.values():
        if activity.id in assigned:
            continue
        store.set_activity_shoe(activity.id, shoe_id)
        count += 1
    return count


def _ensure_fresh() -> dict[str, Activity]:
    """Rescan if files changed, then return the cache."""
    with _lock:
        if _signature != _data_signature():
            _rescan()
        return _activities


def _sorted_activities() -> list[Activity]:
    epoch = datetime.min.replace(tzinfo=timezone.utc)

    def sort_key(a: Activity):
        st = a.start_time
        if st is None:
            return (epoch, a.name)
        return (st.astimezone(timezone.utc), a.name)

    acts = list(_ensure_fresh().values())
    acts.sort(key=sort_key, reverse=True)
    return acts


def _effective_note(act: Activity) -> str:
    db_note = store.get_note(act.id)
    if db_note:
        return db_note
    return act.description or ""


def _summaries() -> list[dict]:
    notes = store.all_notes()
    result = []
    for act in _sorted_activities():
        stats = activity_mod.compute_stats(act)
        note = notes.get(act.id, "") or act.description or ""
        result.append(activity_mod.to_summary(act, note, stats))
    return result


def _global_summary() -> dict:
    total_dist = 0.0
    total_time = 0.0
    total_gain = 0.0
    count = 0
    for act in _sorted_activities():
        stats = activity_mod.compute_stats(act)
        total_dist += stats["distance_m"]
        total_time += stats["moving_time_s"]
        total_gain += stats["elevation_gain_m"]
        count += 1
    return {
        "activities": count,
        "distance_m": round(total_dist),
        "moving_time_s": round(total_time),
        "elevation_gain_m": round(total_gain),
    }


def _activity_analysis(act: Activity) -> dict:
    """Compute all advanced analyses for an activity."""
    return {
        "splits": analysis.compute_splits(act.points),
        "laps": analysis.compute_laps(act),
        "zones": analysis.compute_pace_zones(act.points),
        "gap": analysis.compute_gap(act.points),
        "best_efforts": analysis.compute_best_efforts(act),
    }


def _shoe_by_id(shoe_id: int) -> Optional[dict]:
    for shoe in store.list_shoes():
        if shoe["id"] == shoe_id:
            return shoe
    return None


def _activity_shoe_info(activity_id: str) -> Optional[dict]:
    shoe_id = store.get_activity_shoe(activity_id)
    if shoe_id is None:
        return None
    shoe = _shoe_by_id(shoe_id)
    if shoe is None:
        return None
    return {"id": shoe["id"], "name": shoe["name"]}


def _shoes_with_mileage() -> list[dict]:
    """List shoes with total distance and activity count from assignments."""
    mapping = store.activity_shoe_map()
    dist: dict[int, float] = {}
    count: dict[int, int] = {}
    for act in _sorted_activities():
        shoe_id = mapping.get(act.id)
        if shoe_id is not None:
            stats = activity_mod.compute_stats(act)
            dist[shoe_id] = dist.get(shoe_id, 0.0) + stats["distance_m"]
            count[shoe_id] = count.get(shoe_id, 0) + 1

    result = []
    for shoe in store.list_shoes():
        result.append(
            {
                **shoe,
                "distance_m": round(dist.get(shoe["id"], 0.0), 1),
                "activities_count": count.get(shoe["id"], 0),
            }
        )
    return result


# ---------------------------------------------------------------------------
# Endpoints — activities
# ---------------------------------------------------------------------------
@app.get("/api/summary")
def api_summary() -> dict:
    return _global_summary()


@app.get("/api/activities")
def api_activities() -> dict:
    return {"summary": _global_summary(), "activities": _summaries()}


@app.get("/api/activities/{activity_id}")
def api_activity_detail(activity_id: str) -> dict:
    acts = _ensure_fresh()
    act = acts.get(activity_id)
    if act is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    stats = activity_mod.compute_stats(act)
    note = _effective_note(act)
    detail = activity_mod.to_detail(act, note, stats)
    detail["analysis"] = _activity_analysis(act)
    detail["shoe"] = _activity_shoe_info(act.id)
    detail["rpe"] = store.get_rpe(act.id)
    detail["feedback"] = store.get_feedback(act.id)
    return detail


class NotePayload(BaseModel):
    note: str


@app.put("/api/activities/{activity_id}/note")
def api_update_note(activity_id: str, payload: NotePayload) -> dict:
    acts = _ensure_fresh()
    act = acts.get(activity_id)
    if act is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    note = payload.note.strip()
    store.set_note(activity_id, note)
    return {"id": activity_id, "note": note, "has_note": bool(note)}


# ---------------------------------------------------------------------------
# Endpoints — global analyses
# ---------------------------------------------------------------------------
@app.get("/api/heatmap")
def api_heatmap() -> dict:
    return {"points": analysis.heatmap_points(_sorted_activities())}


@app.get("/api/best-efforts")
def api_best_efforts() -> dict:
    """All-time best efforts over reference distances."""
    best: dict[str, dict] = {}
    for act in _sorted_activities():
        for eff in analysis.compute_best_efforts(act):
            key = eff["label"]
            if key not in best or eff["time_s"] < best[key]["time_s"]:
                best[key] = {
                    "label": eff["label"],
                    "distance_m": eff["distance_m"],
                    "time_s": eff["time_s"],
                    "pace_s_per_km": eff["pace_s_per_km"],
                    "activity_id": act.id,
                    "date": act.start_time.isoformat() if act.start_time else None,
                    "note": _effective_note(act),
                }
    ordered = sorted(best.values(), key=lambda x: x["distance_m"])
    return {"best_efforts": ordered}


@app.get("/api/matched-runs")
def api_matched_runs() -> dict:
    groups = analysis.matched_runs(_sorted_activities())
    result = []
    for group in groups:
        members = []
        for act in group:
            stats = activity_mod.compute_stats(act)
            members.append(
                {
                    "id": act.id,
                    "filename": act.filename,
                    "date": act.start_time.isoformat() if act.start_time else None,
                    "note": _effective_note(act),
                    "distance_m": stats["distance_m"],
                    "moving_time_s": stats["moving_time_s"],
                    "pace_s_per_km": stats["avg_pace_s_per_km"],
                    "elevation_gain_m": stats["elevation_gain_m"],
                }
            )
        result.append(members)
    return {"groups": result}


@app.get("/api/monthly")
def api_monthly() -> dict:
    return {"months": analysis.monthly_stats(_sorted_activities())}


# ---------------------------------------------------------------------------
# Endpoints — goals
# ---------------------------------------------------------------------------
def _period_bounds(
    period: str, now: Optional[datetime] = None
) -> tuple[datetime, datetime]:
    now = now or datetime.now(timezone.utc)
    if period == "weekly":
        start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end = start + timedelta(days=7)
    elif period == "yearly":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = start.replace(year=start.year + 1)
    else:  # monthly
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
    return start, end


def _metric_value(stats: dict, metric: str) -> float:
    return {
        "distance": stats["distance_m"],
        "time": stats["moving_time_s"],
        "elevation": stats["elevation_gain_m"],
    }.get(metric, 0.0)


def _goal_progress(goal: dict, activities: list[Activity]) -> dict:
    start, end = _period_bounds(goal["period"])
    current = 0.0
    for act in activities:
        st = act.start_time
        if st is None:
            continue
        st = st.astimezone(timezone.utc)
        if start <= st < end:
            current += _metric_value(activity_mod.compute_stats(act), goal["metric"])
    target = goal["target"]
    return {
        "current": round(current, 1),
        "target": target,
        "percent": round(100.0 * current / target, 1) if target > 0 else 0.0,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
    }


@app.get("/api/goals")
def api_goals() -> dict:
    activities = _sorted_activities()
    goals = []
    for g in store.list_goals():
        goals.append({**g, "progress": _goal_progress(g, activities)})
    return {"goals": goals}


class GoalPayload(BaseModel):
    period: str
    metric: str
    target: float


@app.post("/api/goals")
def api_create_goal(payload: GoalPayload) -> dict:
    if payload.period not in ("weekly", "monthly", "yearly"):
        raise HTTPException(status_code=400, detail="Invalid period")
    if payload.metric not in ("distance", "time", "elevation"):
        raise HTTPException(status_code=400, detail="Invalid metric")
    goal_id = store.add_goal(payload.period, payload.metric, payload.target)
    return {
        "id": goal_id,
        "period": payload.period,
        "metric": payload.metric,
        "target": payload.target,
    }


@app.put("/api/goals/{goal_id}")
def api_update_goal(goal_id: int, payload: GoalPayload) -> dict:
    store.update_goal(goal_id, payload.period, payload.metric, payload.target)
    return {"id": goal_id}


@app.delete("/api/goals/{goal_id}")
def api_delete_goal(goal_id: int) -> dict:
    store.delete_goal(goal_id)
    return {"deleted": goal_id}


# ---------------------------------------------------------------------------
# Endpoints — profile / weight / shoes
# ---------------------------------------------------------------------------
class ProfilePayload(BaseModel):
    name: str = ""
    height_cm: str = ""
    birth_date: str = ""


@app.get("/api/profile")
def api_profile() -> dict:
    return store.get_profile()


@app.put("/api/profile")
def api_update_profile(payload: ProfilePayload) -> dict:
    store.set_profile(
        {
            "name": payload.name.strip(),
            "height_cm": payload.height_cm.strip(),
            "birth_date": payload.birth_date.strip(),
        }
    )
    return store.get_profile()


class WeightPayload(BaseModel):
    date: str
    weight_kg: float


@app.get("/api/weights")
def api_weights() -> dict:
    weights = store.list_weights()
    return {
        "weights": weights,
        "current_weight_kg": weights[0]["weight_kg"] if weights else None,
    }


@app.post("/api/weights")
def api_add_weight(payload: WeightPayload) -> dict:
    weight_id = store.add_weight(payload.date, payload.weight_kg)
    return {"id": weight_id, "date": payload.date, "weight_kg": payload.weight_kg}


@app.delete("/api/weights/{weight_id}")
def api_delete_weight(weight_id: int) -> dict:
    store.delete_weight(weight_id)
    return {"deleted": weight_id}


class ShoePayload(BaseModel):
    name: str
    notes: str = ""
    threshold_km: float = 600.0


class ShoeUpdatePayload(BaseModel):
    name: str
    notes: str = ""
    threshold_km: float = 600.0
    retired: bool = False


@app.get("/api/shoes")
def api_shoes() -> dict:
    return {"shoes": _shoes_with_mileage()}


@app.post("/api/shoes")
def api_add_shoe(payload: ShoePayload) -> dict:
    shoe_id = store.add_shoe(
        payload.name.strip(), payload.notes.strip(), payload.threshold_km
    )
    return {"id": shoe_id}


@app.put("/api/shoes/{shoe_id}")
def api_update_shoe(shoe_id: int, payload: ShoeUpdatePayload) -> dict:
    store.update_shoe(
        shoe_id,
        payload.name.strip(),
        payload.notes.strip(),
        payload.threshold_km,
        1 if payload.retired else 0,
    )
    return {"id": shoe_id}


@app.delete("/api/shoes/{shoe_id}")
def api_delete_shoe(shoe_id: int) -> dict:
    store.delete_shoe(shoe_id)
    return {"deleted": shoe_id}


class ActivityShoePayload(BaseModel):
    shoe_id: Optional[int] = None


@app.put("/api/activities/{activity_id}/shoe")
def api_set_activity_shoe(activity_id: str, payload: ActivityShoePayload) -> dict:
    acts = _ensure_fresh()
    if activity_id not in acts:
        raise HTTPException(status_code=404, detail="Activity not found")
    store.set_activity_shoe(activity_id, payload.shoe_id)
    return {"activity_id": activity_id, "shoe": _activity_shoe_info(activity_id)}


class DefaultShoePayload(BaseModel):
    shoe_id: Optional[int] = None
    auto_assign: bool = False


@app.get("/api/shoes/default")
def api_default_shoe() -> dict:
    profile = store.get_profile()
    raw = profile.get("default_shoe_id") or ""
    return {
        "shoe_id": int(raw) if raw.isdigit() else None,
        "auto_assign": profile.get("auto_assign_shoe") == "1",
    }


@app.put("/api/shoes/default")
def api_set_default_shoe(payload: DefaultShoePayload) -> dict:
    """Choose the shoe assigned to new runs, and whether to assign it at all."""
    if payload.shoe_id is not None:
        if not any(s["id"] == payload.shoe_id for s in store.list_shoes()):
            raise HTTPException(status_code=404, detail="Shoe not found")
    store.set_profile(
        {
            "default_shoe_id": str(payload.shoe_id) if payload.shoe_id else "",
            "auto_assign_shoe": "1" if payload.auto_assign else "0",
        }
    )
    assigned = _apply_auto_shoe(_ensure_fresh())
    return {
        "shoe_id": payload.shoe_id,
        "auto_assign": payload.auto_assign,
        "assigned": assigned,
    }


# ---------------------------------------------------------------------------
# Endpoints — RPE (session rating of perceived exertion)
# ---------------------------------------------------------------------------
class RpePayload(BaseModel):
    rpe: Optional[int] = None  # 0-10 (Foster CR-10); None clears the value


@app.put("/api/activities/{activity_id}/rpe")
def api_set_activity_rpe(activity_id: str, payload: RpePayload) -> dict:
    acts = _ensure_fresh()
    if activity_id not in acts:
        raise HTTPException(status_code=404, detail="Activity not found")
    rpe = payload.rpe
    if rpe is not None and not (0 <= rpe <= 10):
        raise HTTPException(status_code=400, detail="RPE must be between 1 and 10")
    store.set_rpe(activity_id, rpe)
    return {"activity_id": activity_id, "rpe": rpe}


# ---------------------------------------------------------------------------
# Endpoints — post-run feedback (subjective enrichment)
# ---------------------------------------------------------------------------
class FeedbackPayload(BaseModel):
    session_type: str = ""
    surface: str = ""
    completed: str = ""
    readiness: Optional[int] = None
    sleep_quality: Optional[int] = None
    stress: Optional[int] = None
    legs: Optional[int] = None
    pain: bool = False
    pain_location: str = ""
    pain_side: str = ""
    pain_severity: Optional[int] = None
    pain_timing: str = ""
    pain_trend: str = ""
    conditions: str = ""
    is_race: bool = False
    rpe: Optional[int] = None


def _check_enum(name: str, value: str, allowed) -> None:
    if value and value not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid {name}: {value}")


def _validate_feedback(payload: FeedbackPayload) -> None:
    _check_enum("session_type", payload.session_type, FEEDBACK_SESSION_TYPES)
    _check_enum("surface", payload.surface, FEEDBACK_SURFACES)
    _check_enum("conditions", payload.conditions, FEEDBACK_CONDITIONS)
    _check_enum("completed", payload.completed, FEEDBACK_COMPLETION)
    _check_enum("pain_location", payload.pain_location, FEEDBACK_PAIN_LOCATIONS)
    _check_enum("pain_side", payload.pain_side, FEEDBACK_PAIN_SIDES)
    _check_enum("pain_timing", payload.pain_timing, FEEDBACK_PAIN_TIMINGS)
    _check_enum("pain_trend", payload.pain_trend, FEEDBACK_PAIN_TRENDS)
    for name, value in (
        ("readiness", payload.readiness),
        ("sleep_quality", payload.sleep_quality),
        ("stress", payload.stress),
        ("legs", payload.legs),
    ):
        if value is not None and not (1 <= value <= 5):
            raise HTTPException(
                status_code=400, detail=f"{name} must be between 1 and 5"
            )
    if payload.pain_severity is not None and not (0 <= payload.pain_severity <= 10):
        raise HTTPException(
            status_code=400, detail="pain_severity must be between 0 and 10"
        )
    if payload.rpe is not None and not (0 <= payload.rpe <= 10):
        raise HTTPException(status_code=400, detail="rpe must be between 0 and 10")


@app.get("/api/activities/{activity_id}/feedback")
def api_get_feedback(activity_id: str) -> dict:
    acts = _ensure_fresh()
    if activity_id not in acts:
        raise HTTPException(status_code=404, detail="Activity not found")
    return {
        "feedback": store.get_feedback(activity_id),
        "rpe": store.get_rpe(activity_id),
    }


@app.put("/api/activities/{activity_id}/feedback")
def api_set_feedback(activity_id: str, payload: FeedbackPayload) -> dict:
    acts = _ensure_fresh()
    if activity_id not in acts:
        raise HTTPException(status_code=404, detail="Activity not found")
    _validate_feedback(payload)
    store.set_feedback(activity_id, payload.model_dump(exclude={"rpe"}))
    store.set_rpe(activity_id, payload.rpe)
    return {
        "feedback": store.get_feedback(activity_id),
        "rpe": store.get_rpe(activity_id),
    }


# ---------------------------------------------------------------------------
# Endpoints — support sessions (strength, mobility, cross-training, rest)
# ---------------------------------------------------------------------------
class ExercisePayload(BaseModel):
    name: str
    sets: Optional[int] = None
    reps: Optional[int] = None
    weight_kg: Optional[float] = None
    duration_s: Optional[int] = None
    notes: str = ""


class SessionPayload(BaseModel):
    date: str
    time: str = ""
    kind: str = "other"
    title: str = ""
    duration_min: Optional[int] = None
    rpe: Optional[int] = None
    focus: list[str] = []
    notes: str = ""
    status: str = "completed"
    exercises: list[ExercisePayload] = []


def _validate_session(payload: SessionPayload) -> None:
    _check_enum("kind", payload.kind, SESSION_KINDS)
    _check_enum("status", payload.status, SESSION_STATUS)
    if payload.duration_min is not None and payload.duration_min < 0:
        raise HTTPException(status_code=400, detail="duration_min must be >= 0")
    if payload.rpe is not None and not (0 <= payload.rpe <= 10):
        raise HTTPException(status_code=400, detail="rpe must be between 0 and 10")
    for area in payload.focus or []:
        if area not in SESSION_BODY_AREAS:
            raise HTTPException(status_code=400, detail=f"Invalid focus area: {area}")
    for exercise in payload.exercises or []:
        if not exercise.name.strip():
            raise HTTPException(status_code=400, detail="Exercise name is required")
        for value, label in (
            (exercise.sets, "sets"),
            (exercise.reps, "reps"),
            (exercise.duration_s, "duration_s"),
        ):
            if value is not None and value < 0:
                raise HTTPException(status_code=400, detail=f"{label} must be >= 0")
    try:
        datetime.strptime(payload.date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date")


def _with_muscles(session: dict) -> dict:
    """Attach the classified muscle groups to a session's exercises."""
    for exercise in session.get("exercises") or []:
        exercise["muscles"] = exercises_mod.classify_exercise(exercise["name"])[
            "muscles"
        ]
    return session


@app.get("/api/sessions")
def api_sessions(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    plan_id: Optional[int] = None,
) -> dict:
    sessions = store.list_sessions(date_from, date_to, plan_id)
    return {"sessions": [_with_muscles(session) for session in sessions]}


@app.post("/api/sessions")
def api_add_session(payload: SessionPayload) -> dict:
    _validate_session(payload)
    session_id = store.add_session(payload.model_dump())
    return _with_muscles(store.get_session(session_id))


@app.put("/api/sessions/{session_id}")
def api_update_session(session_id: int, payload: SessionPayload) -> dict:
    _validate_session(payload)
    if store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    store.update_session(session_id, payload.model_dump())
    return _with_muscles(store.get_session(session_id))


@app.delete("/api/sessions/{session_id}")
def api_delete_session(session_id: int) -> dict:
    store.delete_session(session_id)
    return {"deleted": session_id}


# ---------------------------------------------------------------------------
# Endpoints — injuries
# ---------------------------------------------------------------------------
class InjuryVerdictPayload(BaseModel):
    location: str
    side: str = ""
    first_date: str
    verdict: str = ""


@app.get("/api/injuries")
def api_injuries() -> dict:
    """Injury episodes derived from post-run pain reports, plus session links."""
    activities = _sorted_activities()
    dates = {
        activity.id: activity.start_time.astimezone(timezone.utc).date().isoformat()
        for activity in activities
        if activity.start_time
    }
    episodes = injuries.build_episodes(store.all_feedback(), dates)
    linked = injuries.link_sessions_to_episodes(
        episodes,
        store.list_sessions(),
        today=datetime.now(timezone.utc).date(),
        verdicts=store.injury_verdicts(),
    )
    return {"episodes": episodes, **linked}


@app.put("/api/injuries/verdict")
def api_set_injury_verdict(payload: InjuryVerdictPayload) -> dict:
    """Record the athlete's own judgement on a suggested link."""
    _check_enum("verdict", payload.verdict, ("", "plausible", "coincidence"))
    store.set_injury_verdict(
        payload.location, payload.side, payload.first_date, payload.verdict
    )
    return {
        "location": payload.location,
        "side": payload.side,
        "first_date": payload.first_date,
        "verdict": payload.verdict,
    }


# ---------------------------------------------------------------------------
# Endpoints — fuel & recovery (optional daily check-in + supplements)
# ---------------------------------------------------------------------------
class NutritionPayload(BaseModel):
    hydration_l: Optional[float] = None
    energy: Optional[int] = None
    appetite: Optional[int] = None
    steps: Optional[int] = None
    fueling_before: bool = False
    fueling_during: bool = False
    fueling_after: bool = False
    fueling_notes: str = ""
    supplements_taken: list[int] = []
    notes: str = ""


def _validate_nutrition(payload: NutritionPayload) -> None:
    if payload.hydration_l is not None and not (
        0 <= payload.hydration_l <= NUTRITION_HYDRATION_MAX_L
    ):
        raise HTTPException(status_code=400, detail="hydration_l out of range")
    for name, value in (("energy", payload.energy), ("appetite", payload.appetite)):
        if value is not None and not (
            NUTRITION_ENERGY_MIN <= value <= NUTRITION_ENERGY_MAX
        ):
            raise HTTPException(
                status_code=400, detail=f"{name} must be between 1 and 5"
            )
    if payload.steps is not None and not (0 <= payload.steps <= 100000):
        raise HTTPException(
            status_code=400, detail="steps must be between 0 and 100000"
        )


@app.get("/api/nutrition")
def api_nutrition(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> dict:
    return {"logs": store.list_nutrition(date_from, date_to)}


@app.put("/api/nutrition/{date}")
def api_upsert_nutrition(date: str, payload: NutritionPayload) -> dict:
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date")
    _validate_nutrition(payload)
    record = store.upsert_nutrition(date, payload.model_dump())
    return record or {}


@app.delete("/api/nutrition/{record_id}")
def api_delete_nutrition(record_id: int) -> dict:
    store.delete_nutrition(record_id)
    return {"deleted": record_id}


class SupplementPayload(BaseModel):
    name: str
    dose: str = ""
    frequency: str = "daily"
    active: bool = True


def _validate_supplement(payload: SupplementPayload) -> None:
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Supplement name is required")
    if payload.frequency not in SUPPLEMENT_FREQUENCIES:
        raise HTTPException(status_code=400, detail="Invalid frequency")


@app.get("/api/supplements")
def api_supplements() -> dict:
    return {"supplements": store.list_supplements()}


@app.post("/api/supplements")
def api_add_supplement(payload: SupplementPayload) -> dict:
    _validate_supplement(payload)
    supplement_id = store.add_supplement(
        payload.name.strip(), payload.dose.strip(), payload.frequency
    )
    return {"id": supplement_id}


@app.put("/api/supplements/{supplement_id}")
def api_update_supplement(supplement_id: int, payload: SupplementPayload) -> dict:
    _validate_supplement(payload)
    store.update_supplement(
        supplement_id,
        payload.name.strip(),
        payload.dose.strip(),
        payload.frequency,
        payload.active,
    )
    return {"id": supplement_id}


@app.delete("/api/supplements/{supplement_id}")
def api_delete_supplement(supplement_id: int) -> dict:
    store.delete_supplement(supplement_id)
    return {"deleted": supplement_id}


# ---------------------------------------------------------------------------
# Endpoints — coaching
# ---------------------------------------------------------------------------
def _rpe_map() -> dict[str, int]:
    return store.all_rpe()


@app.get("/api/coaching/load")
def api_coaching_load() -> dict:
    activities = _sorted_activities()
    rpe_map = _rpe_map()
    series = coaching.full_load_series(activities, rpe_map)
    return {
        "days": series,
        "zones": coaching.zone_definitions(),
        "current": series[-1] if series else None,
        "divergence": coaching.load_divergence(activities, rpe_map),
    }


@app.get("/api/coaching/fitness")
def api_coaching_fitness() -> dict:
    return coaching.fitness_series(_sorted_activities(), _rpe_map())


@app.get("/api/coaching/acwr")
def api_coaching_acwr() -> dict:
    return coaching.acwr_series(_sorted_activities(), _rpe_map())


@app.get("/api/coaching/intensity")
def api_coaching_intensity() -> dict:
    data = coaching.intensity_distribution(_sorted_activities())
    data["basis"] = "grade-adjusted pace"
    return data


@app.get("/api/coaching/vo2max")
def api_coaching_vo2max() -> dict:
    activities = _sorted_activities()
    return {
        **coaching.vo2max_and_predictions(activities),
        **coaching.performance_profile(activities),
    }


@app.get("/api/coaching/plans")
def api_coaching_plans() -> dict:
    return {"plans": store.list_plans()}


@app.get("/api/coaching/plans/{plan_id}")
def api_coaching_plan(plan_id: int) -> dict:
    plan = store.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


class PlanPayload(BaseModel):
    name: str = ""
    goal_distance_m: Optional[float] = None
    goal_date: Optional[str] = None
    weekly_target_m: Optional[float] = None
    weekly_target_s: Optional[float] = None
    sessions_per_week: int = PLAN_DEFAULT_SESSIONS
    start_date: Optional[str] = None


@app.post("/api/coaching/plans")
def api_coaching_generate_plan(payload: PlanPayload) -> dict:
    activities = _sorted_activities()
    rpe_map = _rpe_map()
    data = coaching.generate_plan(
        activities,
        name=payload.name,
        goal_distance_m=payload.goal_distance_m,
        goal_date=payload.goal_date,
        weekly_target_m=payload.weekly_target_m,
        weekly_target_s=payload.weekly_target_s,
        sessions_per_week=payload.sessions_per_week,
        start_date=payload.start_date,
    )
    current = coaching.fitness_series(activities, rpe_map)["current"]
    data["projection"] = coaching.project_plan(data, current["ctl"] if current else 0.0)
    plan_id = store.add_plan(
        data["name"], data["goal_description"], data["weeks"], data
    )
    # Materialize the plan's support sessions so they appear in the planner.
    for session in data.get("support_sessions", []):
        store.add_session({**session, "source": "plan", "plan_id": plan_id})
    return {**data, "id": plan_id}


@app.delete("/api/coaching/plans/{plan_id}")
def api_coaching_delete_plan(plan_id: int) -> dict:
    store.delete_plan(plan_id)
    return {"deleted": plan_id}


# ---------------------------------------------------------------------------
# Endpoints — coaching assistant (optional LLM)
# ---------------------------------------------------------------------------
def _coach_snapshot() -> dict:
    """Assemble the compact athlete snapshot used by the coach endpoints."""
    acts = _sorted_activities()
    goals = [{**g, "progress": _goal_progress(g, acts)} for g in store.list_goals()]
    return coaching.build_snapshot(
        acts,
        _rpe_map(),
        store.get_profile(),
        store.list_weights(),
        _shoes_with_mileage(),
        goals,
        store.all_notes(),
        feedback_map=store.all_feedback(),
        sessions=store.list_sessions(),
        nutrition=store.list_nutrition(),
        supplements=store.list_supplements(),
    )


def _coach_tool_context() -> dict:
    """Data the coach's read-only tools may query, built once per request."""
    return {
        "activities": _sorted_activities(),
        "rpe": _rpe_map(),
        "feedback": store.all_feedback(),
        "notes": store.all_notes(),
        "sessions": store.list_sessions(),
    }


@app.get("/api/coaching/insights")
def api_coaching_insights() -> dict:
    snapshot = _coach_snapshot()
    return {
        "insights": coaching.rule_based_insights(snapshot),
        "generated_at": snapshot["generated_at"],
    }


@app.get("/api/coaching/chat/status")
def api_coaching_chat_status() -> dict:
    return {
        "configured": coach_llm.llm_configured(),
        "models": coach_llm.list_models(),
        "default": coach_llm.default_model_id(),
    }


class ModelPayload(BaseModel):
    name: str
    model: str
    apiBase: str
    apiKey: str = ""
    chatPath: str = ""


@app.post("/api/coaching/models")
def api_add_model(payload: ModelPayload) -> dict:
    """Register a model from the UI.

    The key is written to the local .env and never returned: the response only
    says whether the model is configured.
    """
    try:
        return coach_llm.add_model(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/coaching/models/{model_id}")
def api_remove_model(model_id: str) -> dict:
    if not coach_llm.remove_model(model_id):
        raise HTTPException(
            status_code=404, detail="Model not found, or it is a shipped model"
        )
    return {"removed": model_id}


class CoachChatPayload(BaseModel):
    message: str
    history: list[dict] = []
    model: Optional[str] = None


@app.post("/api/coaching/chat")
def api_coaching_chat(payload: CoachChatPayload) -> dict:
    if not coach_llm.llm_configured(payload.model):
        raise HTTPException(status_code=503, detail="This AI model is not configured.")
    message = (payload.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Empty message.")
    snapshot = _coach_snapshot()
    try:
        reply = coach_llm.chat(
            snapshot,
            payload.history,
            message,
            payload.model,
            tool_context=_coach_tool_context(),
        )
    except coach_llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"reply": reply}


class CoachReviewPayload(BaseModel):
    model: Optional[str] = None


@app.post("/api/coaching/review")
def api_coaching_review(payload: Optional[CoachReviewPayload] = None) -> dict:
    model_id = payload.model if payload else None
    if not coach_llm.llm_configured(model_id):
        raise HTTPException(status_code=503, detail="This AI model is not configured.")
    snapshot = _coach_snapshot()
    try:
        review = coach_llm.review(snapshot, model_id)
    except coach_llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"review": review}


# ---------------------------------------------------------------------------
# Race-day pacing
# ---------------------------------------------------------------------------
@app.post("/api/coaching/pacing")
async def api_coaching_pacing(
    request: Request, target_time_s: int, step_m: int = 200
) -> dict:
    """Build a constant-effort pacing plan from a course GPX.

    The course is parsed in memory and discarded: a route is not an activity and
    must not appear in the log.
    """
    if not 300 <= target_time_s <= 86_400:
        raise HTTPException(
            status_code=400, detail="Target time must be between 5 minutes and 24 hours"
        )
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty course file")
    if len(body) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Course file is too large")

    handle = tempfile.NamedTemporaryFile(suffix=".gpx", delete=False)
    try:
        handle.write(body)
        handle.close()
        points = pacing.read_route(Path(handle.name))
        if len(points) < 2:
            raise HTTPException(
                status_code=422,
                detail="No track or route points found in the file",
            )
        plan = pacing.build_plan(
            points, target_time_s, step_m=max(50, min(1000, step_m))
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not read the course: {exc}")
    finally:
        Path(handle.name).unlink(missing_ok=True)

    return plan


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------
def _report_data() -> dict:
    """Assemble everything the report renders (see app/report.py)."""
    activities = _sorted_activities()
    rpe_map = _rpe_map()
    dates = {
        activity.id: activity.start_time.astimezone(timezone.utc).date().isoformat()
        for activity in activities
        if activity.start_time
    }
    episodes = injuries.build_episodes(store.all_feedback(), dates)
    linked = injuries.link_sessions_to_episodes(
        episodes,
        store.list_sessions(),
        today=datetime.now(timezone.utc).date(),
        verdicts=store.injury_verdicts(),
    )

    totals = {"activities": len(activities)}
    for activity in activities:
        stats = activity_mod.compute_stats(activity)
        for key in ("distance_m", "moving_time_s", "elevation_gain_m"):
            totals[key] = totals.get(key, 0.0) + stats[key]

    current = coaching.fitness_series(activities, rpe_map)["current"] or {}
    intensity = coaching.intensity_distribution(activities)["rolling"]["groups"]
    dated = [a.start_time for a in activities if a.start_time]

    return report_mod.build(
        {
            "profile": store.get_profile(),
            "totals": totals,
            "window": {
                "start": min(dated).date().isoformat() if dated else None,
                "end": max(dated).date().isoformat() if dated else None,
            },
            "load": current,
            "intensity": intensity,
            "injuries": {**linked, "episodes": episodes},
            "sessions": store.list_sessions(),
            "shoes": _shoes_with_mileage(),
        }
    )


@app.get("/api/export/markdown")
def api_export_markdown() -> PlainTextResponse:
    """Download the report as Markdown (for a coach, a physio, or an archive)."""
    text = report_mod.markdown(_report_data())
    filename = f"training-report-{datetime.now(timezone.utc).date().isoformat()}.md"
    return PlainTextResponse(
        text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/report")
def report_page() -> HTMLResponse:
    """Print-styled report: the browser's Save as PDF produces the document."""
    return HTMLResponse(report_mod.html(_report_data()))


# ---------------------------------------------------------------------------
# Uploads (drag and drop)
# ---------------------------------------------------------------------------
@app.post("/api/upload/{category}")
async def api_upload(category: str, filename: str, request: Request) -> dict:
    """Store an uploaded file in the matching data/ folder and import it.

    The file is sent as a raw request body rather than multipart/form-data, so
    the runtime keeps its two dependencies (python-multipart is not needed).
    All validation lives in app/uploads.py.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="File is too large")

    body = await request.body()
    try:
        stored = uploads_mod.store_upload(category, filename, body)
    except uploads_mod.UploadError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)

    name = stored["filename"]
    if category == "running":
        acts = _ensure_fresh()
        activity = next((a for a in acts.values() if a.filename == name), None)
        summary = activity.name if activity else "file stored, no activity parsed"
    elif category == "nutrition":
        stats = connectors_mod.import_nutrition_dir(store, DATA_NUTRITION_DIR)
        summary = f"{stats['logs']} day(s) of nutrition, {stats['weights']} weight(s)"
    else:
        stats = connectors_mod.import_workout_dir(store, DATA_WORKOUT_DIR)
        summary = f"{stats['sessions']} session(s)"

    return {
        "category": category,
        "filename": name,
        "bytes": stored["bytes"],
        "replaced": stored["replaced"],
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
@app.get("/api/data-version")
def api_data_version() -> dict:
    """Cheap fingerprint of the data folders, polled by the UI."""
    version = hashlib.sha1(repr(_data_signature()).encode()).hexdigest()[:12]
    return {"version": version, "watcher_seconds": DATA_WATCH_SECONDS}


@app.post("/api/reload")
def api_reload() -> dict:
    with _lock:
        _rescan()
    return {"activities": len(_activities)}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
