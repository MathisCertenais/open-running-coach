"""Tests for session exercises persistence and the default-shoe rule."""

from __future__ import annotations

import pytest

from app.store import Store


@pytest.fixture()
def store(tmp_path):
    return Store(tmp_path / "test.db")


def test_exercises_are_saved_with_a_session(store):
    session_id = store.add_session(
        {
            "date": "2026-10-20",
            "kind": "strength",
            "title": "Lower body",
            "exercises": [
                {"name": "Leg press", "sets": 3, "reps": 10, "weight_kg": 80},
                {"name": "Leg extension", "sets": 3, "reps": 12, "weight_kg": 30},
            ],
        }
    )

    exercises = store.get_session(session_id)["exercises"]

    assert [e["name"] for e in exercises] == ["Leg press", "Leg extension"]
    assert exercises[0]["sets"] == 3
    assert exercises[0]["weight_kg"] == 80.0
    assert [e["position"] for e in exercises] == [0, 1]


def test_exercises_without_a_name_are_dropped(store):
    session_id = store.add_session(
        {
            "date": "2026-10-20",
            "kind": "strength",
            "exercises": [{"name": "  "}, {"name": "Squat"}],
        }
    )

    assert [e["name"] for e in store.get_session(session_id)["exercises"]] == ["Squat"]


def test_updating_a_session_replaces_its_exercises(store):
    session_id = store.add_session(
        {"date": "2026-10-20", "kind": "strength", "exercises": [{"name": "Squat"}]}
    )

    store.update_session(
        session_id,
        {"date": "2026-10-20", "kind": "strength", "exercises": [{"name": "Deadlift"}]},
    )

    names = [e["name"] for e in store.get_session(session_id)["exercises"]]
    assert names == ["Deadlift"]


def test_omitting_exercises_leaves_them_untouched(store):
    session_id = store.add_session(
        {"date": "2026-10-20", "kind": "strength", "exercises": [{"name": "Squat"}]}
    )

    store.update_session(session_id, {"date": "2026-10-20", "kind": "strength"})

    assert [e["name"] for e in store.get_session(session_id)["exercises"]] == ["Squat"]


def test_deleting_a_session_deletes_its_exercises(store):
    session_id = store.add_session(
        {"date": "2026-10-20", "kind": "strength", "exercises": [{"name": "Squat"}]}
    )

    store.delete_session(session_id)

    count = store._conn.execute("SELECT COUNT(*) FROM session_exercises").fetchone()[0]
    assert count == 0


def test_sessions_list_carries_their_exercises(store):
    store.add_session(
        {"date": "2026-10-20", "kind": "strength", "exercises": [{"name": "Squat"}]}
    )

    assert store.list_sessions()[0]["exercises"][0]["name"] == "Squat"


def test_orphan_cleanup_removes_exercises_of_deleted_sessions(store):
    session_id = store.add_session(
        {"date": "2026-10-20", "kind": "strength", "exercises": [{"name": "Squat"}]}
    )
    store._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    store.delete_orphan_exercises()

    count = store._conn.execute("SELECT COUNT(*) FROM session_exercises").fetchone()[0]
    assert count == 0


# ---------------------------------------------------------------------------
# Default shoe settings
# ---------------------------------------------------------------------------
def test_default_shoe_settings_round_trip(store):
    store.set_profile({"default_shoe_id": "4", "auto_assign_shoe": "1"})

    profile = store.get_profile()

    assert profile["default_shoe_id"] == "4"
    assert profile["auto_assign_shoe"] == "1"


def test_profile_reads_survive_repeated_access(store):
    store.set_profile({"default_shoe_id": "2"})

    for _ in range(5):
        assert store.get_profile()["default_shoe_id"] == "2"
