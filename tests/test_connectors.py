"""Tests for the file connectors: nutrition, steps, weight and workouts.

These cover the promise from ADR-0004: a file is imported once, re-importing the
same file changes nothing, and a re-imported changed file replaces what it
previously produced.
"""

from __future__ import annotations

import pytest

from app.connectors import import_nutrition_dir, import_workout_dir
from app.store import Store
from tests.fixtures.make_nutrition import (
    CSV_ROWS,
    JSON_DAYS,
    write_nutrition_csv,
    write_nutrition_json,
)
from tests.fixtures.make_workout import WORKOUTS, write_workout_csv, write_workout_json


@pytest.fixture()
def store(tmp_path):
    return Store(tmp_path / "test.db")


@pytest.fixture()
def nutrition_dir(tmp_path):
    directory = tmp_path / "nutrition"
    directory.mkdir()
    return directory


@pytest.fixture()
def workout_dir(tmp_path):
    directory = tmp_path / "workout"
    directory.mkdir()
    return directory


# ---------------------------------------------------------------------------
# Nutrition, weight and steps
# ---------------------------------------------------------------------------
def test_nutrition_csv_imports_every_day(store, nutrition_dir):
    write_nutrition_csv(nutrition_dir / "waistline.csv")

    stats = import_nutrition_dir(store, nutrition_dir)

    assert stats == {"files": 1, "logs": len(CSV_ROWS), "weights": len(CSV_ROWS)}


def test_nutrition_csv_parses_french_headers_and_decimal_comma(store, nutrition_dir):
    write_nutrition_csv(nutrition_dir / "waistline.csv")
    import_nutrition_dir(store, nutrition_dir)

    day = store.get_nutrition("2026-10-20")

    assert day is not None
    assert day["steps"] == 2800
    macros = day["macros"]
    assert macros["calories"] == pytest.approx(2100)
    assert macros["protein_g"] == pytest.approx(120)
    assert macros["carbs_g"] == pytest.approx(260)
    assert macros["fat_g"] == pytest.approx(70)


def test_weight_is_stored_with_the_decimal_point(store, nutrition_dir):
    write_nutrition_csv(nutrition_dir / "waistline.csv")
    import_nutrition_dir(store, nutrition_dir)

    weights = {w["date"]: w["weight_kg"] for w in store.list_weights()}

    assert weights["2026-10-20"] == pytest.approx(72.4)
    assert weights["2026-10-22"] == pytest.approx(71.8)


def test_steps_are_stored_per_day(store, nutrition_dir):
    write_nutrition_csv(nutrition_dir / "waistline.csv")
    import_nutrition_dir(store, nutrition_dir)

    logs = {row["date"]: row for row in store.list_nutrition()}

    assert logs["2026-10-21"]["steps"] == 3500
    assert logs["2026-10-22"]["steps"] == 2100


def test_reimporting_an_unchanged_file_is_a_no_op(store, nutrition_dir):
    path = write_nutrition_csv(nutrition_dir / "waistline.csv")
    first = import_nutrition_dir(store, nutrition_dir)

    second = import_nutrition_dir(store, nutrition_dir)

    assert first["files"] == 1
    assert second == {"files": 0, "logs": 0, "weights": 0}
    assert len(store.list_nutrition()) == len(CSV_ROWS)
    assert len(store.list_weights()) == len(CSV_ROWS)
    assert path.exists()


def test_a_changed_file_is_reimported_without_duplicating_days(store, nutrition_dir):
    path = write_nutrition_csv(nutrition_dir / "waistline.csv")
    import_nutrition_dir(store, nutrition_dir)

    # Rewrite with a different step count and a newer mtime.
    text = path.read_text(encoding="utf-8-sig").replace("2800", "9999")
    path.write_text(text, encoding="utf-8")
    stats = import_nutrition_dir(store, nutrition_dir)

    assert stats["files"] == 1
    logs = {row["date"]: row for row in store.list_nutrition()}
    assert len(logs) == len(CSV_ROWS)
    assert logs["2026-10-20"]["steps"] == 9999


def test_nutrition_json_is_accepted(store, nutrition_dir):
    write_nutrition_json(nutrition_dir / "export.json")

    stats = import_nutrition_dir(store, nutrition_dir)

    assert stats["logs"] == len(JSON_DAYS)
    assert stats["weights"] == len(JSON_DAYS)


def test_unsupported_files_are_ignored(store, nutrition_dir):
    (nutrition_dir / "notes.txt").write_text("ignore me", encoding="utf-8")

    assert import_nutrition_dir(store, nutrition_dir)["files"] == 0


def test_a_missing_directory_is_harmless(store, tmp_path):
    assert import_nutrition_dir(store, tmp_path / "nope") == {
        "files": 0,
        "logs": 0,
        "weights": 0,
    }


# ---------------------------------------------------------------------------
# Workouts
# ---------------------------------------------------------------------------
def test_workout_json_imports_every_session(store, workout_dir):
    write_workout_json(workout_dir / "wger.json")

    stats = import_workout_dir(store, workout_dir)

    assert stats["sessions"] == sum(len(w["sessions"]) for w in WORKOUTS)


def test_workout_json_summarises_the_exercises(store, workout_dir):
    write_workout_json(workout_dir / "wger.json")
    import_workout_dir(store, workout_dir)

    sessions = {s["date"]: s for s in store.list_sessions()}

    assert "Bench press 3x8 @ 60 kg" in sessions["2026-10-20"]["notes"]
    assert "Squat 4x6 @ 80 kg" in sessions["2026-10-22"]["notes"]


def test_workout_json_defaults_to_strength(store, workout_dir):
    write_workout_json(workout_dir / "wger.json")
    import_workout_dir(store, workout_dir)

    kinds = {s["date"]: s["kind"] for s in store.list_sessions()}

    assert kinds["2026-10-20"] == "strength"
    assert kinds["2026-10-22"] == "strength"


def test_workout_csv_is_accepted(store, workout_dir):
    write_workout_csv(workout_dir / "sessions.csv")

    stats = import_workout_dir(store, workout_dir)

    assert stats["sessions"] == 2
    kinds = {s["date"]: s["kind"] for s in store.list_sessions()}
    assert kinds == {"2026-10-21": "mobility", "2026-10-23": "rest"}


def test_reimporting_an_unchanged_workout_file_is_a_no_op(store, workout_dir):
    write_workout_json(workout_dir / "wger.json")
    first = import_workout_dir(store, workout_dir)

    second = import_workout_dir(store, workout_dir)

    assert first["files"] == 1
    assert second == {"files": 0, "sessions": 0}


def test_a_changed_workout_file_replaces_its_sessions(store, workout_dir):
    path = write_workout_json(workout_dir / "wger.json")
    import_workout_dir(store, workout_dir)
    before = len(store.list_sessions())

    path.write_text(
        path.read_text(encoding="utf-8").replace("Upper body", "Upper body v2"),
        encoding="utf-8",
    )
    import_workout_dir(store, workout_dir)

    # Same number of sessions: replacement, not duplication.
    assert len(store.list_sessions()) == before
