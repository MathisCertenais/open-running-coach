"""Generic, format-tolerant CSV/JSON importers.

Designed to accept exports from different apps with minimal mapping:

- Nutrition CSV: `,` or `;` separated, English or French headers, ISO or
  `DD/MM/YYYY` dates, optional unit suffixes ("Calories (kcal)").
  Tested against Waistline's semicolon/French diary export.
- Workout CSV/JSON: generic session list, or a wger-style
  `{"workouts": [{"name": ..., "sessions": [...]}]}` object with `exercises`.

Rows are aggregated per day for nutrition and deduplicated by the import
tracker (see app/connectors/__init__.py).
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional

NUTRITION_COLUMNS = {
    "date": ("date", "day", "jour"),
    "calories": ("calories", "kcal", "calorie", "energy", "energie"),
    "protein_g": ("protein", "proteins", "proteines", "protides", "protein_g"),
    "carbs_g": ("carbs", "carbohydrates", "carbohydrate", "glucides", "carbs_g"),
    "fat_g": ("fat", "fats", "lipides", "graisses", "fat_g"),
    "weight_kg": ("weight", "weight_kg", "poids", "masse"),
    "steps": ("steps", "step_count", "daily_steps", "pas"),
}

WORKOUT_COLUMNS = {
    "date": ("date", "day", "jour"),
    "kind": ("kind", "type", "category"),
    "title": ("title", "name", "workout", "seance", "session"),
    "duration_min": ("duration_min", "duration", "minutes", "duree"),
    "rpe": ("rpe", "effort"),
    "focus": ("focus", "body_areas", "muscles", "zones"),
    "notes": ("notes", "note", "comment", "commentaire"),
    "status": ("status", "statut"),
}

SESSION_KINDS = ("strength", "mobility", "cross", "rest", "physio", "other")
SESSION_STATUS = ("planned", "completed", "skipped")


def _norm_header(name) -> str:
    """Normalize a header: drop units, accents, punctuation; lower-case."""
    text = str(name or "")
    text = re.sub(r"\(.*?\)", "", text)  # drop " (kcal)", " (g)", ...
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text


def _pick(row: dict, keys: tuple[str, ...]):
    lowered = {_norm_header(k): v for k, v in row.items()}
    for key in keys:
        if key in lowered and lowered[key] not in (None, ""):
            return lowered[key]
    return None


def _num(value) -> Optional[float]:
    if value is None or value == "":
        return None
    text = str(value).strip().replace(" ", "")
    # Handle "72,4" (French decimal comma) and thousands separators.
    if text.count(",") == 1 and "." not in text:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _int(value) -> Optional[int]:
    number = _num(value)
    return int(round(number)) if number is not None else None


def _day(value) -> Optional[str]:
    """Parse ISO dates and common locale formats (DD/MM/YYYY preferred)."""
    if not value:
        return None
    text = str(value).strip()
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return text[:10]
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _read_csv(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    header = text.splitlines()[0] if text else ""
    delimiter = ";" if header.count(";") > header.count(",") else ","
    return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Nutrition
# ---------------------------------------------------------------------------
def _nutrition_payload(row: dict) -> dict:
    day = _day(_pick(row, NUTRITION_COLUMNS["date"]))
    if not day:
        return {}
    macros = (
        row.get("macros")
        if isinstance(row.get("macros"), dict)
        else {
            key: _num(_pick(row, NUTRITION_COLUMNS[key]))
            for key in ("calories", "protein_g", "carbs_g", "fat_g")
        }
    )
    macros = {k: v for k, v in (macros or {}).items() if v is not None}
    payload = {"date": day}
    if macros:
        payload["macros"] = macros
    weight = _num(_pick(row, NUTRITION_COLUMNS["weight_kg"]))
    if weight:
        payload["weight_kg"] = weight
    steps = _int(_pick(row, NUTRITION_COLUMNS["steps"]))
    if steps is not None:
        payload["steps"] = steps
    return payload


def read_nutrition_csv(path: Path) -> dict:
    return _collect_nutrition(_read_csv(path))


def read_nutrition_json(path: Path) -> dict:
    data = _read_json(path)
    if isinstance(data, dict):
        data = data.get("nutrition") or data.get("logs") or []
    return _collect_nutrition(data if isinstance(data, list) else [])


def _collect_nutrition(rows: list[dict]) -> dict:
    by_date: dict[str, dict] = {}
    steps_by_date: dict[str, int] = {}
    weights: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        payload = _nutrition_payload(row)
        if not payload:
            continue
        day = payload["date"]
        if payload.get("macros"):
            bucket = by_date.setdefault(day, {})
            for key, value in payload["macros"].items():
                bucket[key] = bucket.get(key, 0) + value
        if payload.get("steps") is not None:
            steps_by_date[day] = max(steps_by_date.get(day, 0), payload["steps"])
        if payload.get("weight_kg"):
            weights[day] = payload["weight_kg"]
    nutrition = []
    for day in sorted(set(by_date) | set(steps_by_date)):
        entry = {"date": day, "macros": by_date.get(day, {})}
        if day in steps_by_date:
            entry["steps"] = steps_by_date[day]
        nutrition.append(entry)
    return {
        "nutrition": nutrition,
        "weights": [{"date": day, "weight_kg": kg} for day, kg in weights.items()],
    }


# ---------------------------------------------------------------------------
# Workout / support sessions
# ---------------------------------------------------------------------------
def _exercise_summary(exercises) -> str:
    if not isinstance(exercises, list):
        return ""
    parts = []
    for exercise in exercises:
        if not isinstance(exercise, dict):
            continue
        name = exercise.get("name") or exercise.get("exercise") or ""
        sets = exercise.get("sets")
        reps = exercise.get("reps")
        weight = exercise.get("weight_kg") or exercise.get("weight")
        detail = f"{sets}x{reps}" if sets and reps else ""
        if weight:
            detail = (detail + " @ " if detail else "@ ") + f"{weight} kg"
        parts.append(f"{name} {detail}".strip())
    return "; ".join(part for part in parts if part)


def _normalise_exercises(raw) -> list[dict]:
    """Normalise the exercise list of a workout session.

    Accepts strings ("Leg press") as well as objects with sets/reps/weight, so a
    hand-written export stays importable.
    """
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if isinstance(item, str):
            name = item.strip()
            if name:
                out.append({"name": name})
            continue
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("exercise") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "sets": _int(item.get("sets")),
                "reps": _int(item.get("reps")),
                "weight_kg": _num(item.get("weight_kg") or item.get("weight")),
                "duration_s": _int(item.get("duration_s")),
                "notes": str(item.get("notes") or "").strip(),
            }
        )
    return out


def _session_payload(row: dict) -> Optional[dict]:
    day = _day(_pick(row, WORKOUT_COLUMNS["date"]))
    if not day:
        return None
    focus = _pick(row, WORKOUT_COLUMNS["focus"])
    if isinstance(focus, str):
        focus = [f.strip() for f in focus.replace(",", "|").split("|") if f.strip()]
    elif not isinstance(focus, list):
        focus = []
    kind = (
        str(_pick(row, WORKOUT_COLUMNS["kind"]) or "strength")
        .strip()
        .lower()
        .replace(" ", "_")
    )
    if kind not in SESSION_KINDS:
        kind = "strength"
    status = str(_pick(row, WORKOUT_COLUMNS["status"]) or "completed").strip().lower()
    if status not in SESSION_STATUS:
        status = "completed"
    notes = str(_pick(row, WORKOUT_COLUMNS["notes"]) or "").strip()
    if not notes:
        notes = _exercise_summary(row.get("exercises"))
    return {
        "date": day,
        "time": "",
        "kind": kind,
        "title": str(_pick(row, WORKOUT_COLUMNS["title"]) or "").strip(),
        "duration_min": _int(_pick(row, WORKOUT_COLUMNS["duration_min"])),
        "rpe": _int(_pick(row, WORKOUT_COLUMNS["rpe"])),
        "focus": focus,
        "notes": notes,
        "status": status,
        "exercises": _normalise_exercises(row.get("exercises")),
    }


def read_workout_csv(path: Path) -> list[dict]:
    return _collect_sessions(_read_csv(path))


def read_workout_json(path: Path) -> list[dict]:
    data = _read_json(path)
    if isinstance(data, list):
        return _collect_sessions(data)
    if not isinstance(data, dict):
        return []
    if isinstance(data.get("sessions"), list):
        return _collect_sessions(data["sessions"])
    if isinstance(data.get("workouts"), list):
        sessions = []
        for workout in data["workouts"]:
            if not isinstance(workout, dict):
                continue
            title = workout.get("name") or workout.get("title") or ""
            for session in workout.get("sessions") or []:
                if not isinstance(session, dict):
                    continue
                merged = {**session}
                merged.setdefault("title", title)
                merged.setdefault("kind", "strength")
                sessions.append(merged)
        return _collect_sessions(sessions)
    return []


def _collect_sessions(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        session = _session_payload(row)
        if session:
            out.append(session)
    return out
