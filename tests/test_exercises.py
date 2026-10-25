"""Tests for exercise classification: what each movement loads, and why."""

from __future__ import annotations

import pytest

from app.exercises import (
    LOWER_LIMB_PAIN,
    classify_exercise,
    exercises_loading,
    muscles_for_pain,
)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Leg press", ["quads", "glutes"]),
        ("Leg extension", ["quads"]),
        ("Bulgarian split squat", ["quads", "glutes"]),
        ("Romanian deadlift", ["hamstrings", "glutes"]),
        ("Hip thrust", ["glutes", "hamstrings"]),
        ("Calf raise", ["calves", "achilles"]),
        ("Hip flexor stretch", ["hip_flexors", "hip"]),
        ("Bench press", ["chest", "triceps", "shoulders"]),
        ("Plank", ["core"]),
    ],
)
def test_known_exercises_map_to_muscles(name, expected):
    assert classify_exercise(name)["muscles"] == expected


def test_leg_curl_is_not_read_as_a_biceps_curl():
    # The regression this table exists to prevent: "curl" alone would match.
    info = classify_exercise("Seated leg curl")

    assert info["muscles"] == ["hamstrings"]
    assert info["matched"] == ["leg curl"]


def test_biceps_curl_still_matches_biceps():
    assert classify_exercise("Dumbbell biceps curl")["muscles"] == ["biceps"]


def test_classification_names_the_keyword_that_fired():
    info = classify_exercise("45 degree leg press machine")

    assert info["matched"] == ["leg press"]


def test_unknown_exercises_are_not_guessed():
    info = classify_exercise("Kettlebell flow")

    assert info["muscles"] == []
    assert info["matched"] == []


@pytest.mark.parametrize("name", ["", "   ", "???"])
def test_blank_names_are_safe(name):
    assert classify_exercise(name)["muscles"] == []


def test_accents_and_case_do_not_matter():
    assert classify_exercise("DÉVELOPPÉ")["muscles"] == []


@pytest.mark.parametrize(
    "location, expected",
    [
        ("knee", {"quads", "hamstrings", "glutes"}),
        ("quad", {"quads"}),
        ("achilles", {"achilles", "calves"}),
        ("hip", {"hip", "hip_flexors", "glutes", "adductors"}),
    ],
)
def test_pain_locations_map_to_muscles(location, expected):
    assert set(muscles_for_pain(location)) == expected


def test_unknown_pain_location_has_no_mapping():
    assert muscles_for_pain("elbow") == ()


def test_every_lower_limb_pain_location_has_a_mapping():
    for location in LOWER_LIMB_PAIN:
        assert muscles_for_pain(location), location


def test_exercises_loading_selects_only_matching_movements():
    exercises = [
        {"name": "Leg press"},
        {"name": "Bench press"},
        {"name": "Leg extension"},
    ]

    hits = exercises_loading(("quads",), exercises)

    assert [h["name"] for h in hits] == ["Leg press", "Leg extension"]
    assert all("quads" in h["muscles"] for h in hits)


def test_exercises_loading_without_muscles_returns_nothing():
    assert exercises_loading((), [{"name": "Leg press"}]) == []
