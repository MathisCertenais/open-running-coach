"""Workout export in the wger-style nested shape.

``workouts[].sessions[].exercises[]`` is flattened into support sessions, with
the exercises summarised into the session notes.
"""

from __future__ import annotations

import json
from pathlib import Path

WORKOUTS = [
    {
        "name": "Upper body",
        "sessions": [
            {
                "date": "2026-10-20",
                "duration_min": 45,
                "rpe": 6,
                "focus": ["shoulders", "triceps", "chest"],
                "exercises": [
                    {"name": "Bench press", "sets": 3, "reps": 8, "weight_kg": 60},
                    {"name": "Barbell row", "sets": 3, "reps": 10, "weight_kg": 50},
                ],
            }
        ],
    },
    {
        "name": "Lower body",
        "sessions": [
            {
                "date": "2026-10-22",
                "duration_min": 50,
                "rpe": 7,
                "focus": ["glutes", "quads"],
                "exercises": [
                    {"name": "Squat", "sets": 4, "reps": 6, "weight_kg": 80},
                ],
            }
        ],
    },
]

# Expected notes, produced by the connector's exercise summary.
EXPECTED_NOTES = [
    "Bench press 3x8 @ 60 kg; Barbell row 3x10 @ 50 kg",
    "Squat 4x6 @ 80 kg",
]

CSV_HEADER = "Date;Type;Title;Duration (min);RPE;Focus;Notes"
CSV_ROWS = [
    "2026-10-21;mobility;Hip mobility;20;3;hips;Short session",
    "2026-10-23;rest;Full rest;0;0;;Sleep and hydrate",
]


def workout_json_text() -> str:
    return json.dumps({"workouts": WORKOUTS}, indent=2)


def write_workout_json(path: Path) -> Path:
    """Write a wger-shaped workout export and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(workout_json_text(), encoding="utf-8")
    return path


def workout_csv_text() -> str:
    return "\n".join([CSV_HEADER, *CSV_ROWS]) + "\n"


def write_workout_csv(path: Path) -> Path:
    """Write a generic workout CSV export and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(workout_csv_text(), encoding="utf-8")
    return path
