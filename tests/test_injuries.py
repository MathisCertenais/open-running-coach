"""Tests for derived injury episodes and their link to strength sessions."""

from __future__ import annotations

from datetime import date

from app.config import INJURY_ACTIVE_DAYS, INJURY_EPISODE_GAP_DAYS
from app.injuries import build_episodes, link_sessions_to_episodes

TODAY = date(2026, 4, 30)


def feedback(location="quad", side="left", severity=5, trend="same", pain=True):
    return {
        "pain": pain,
        "pain_location": location,
        "pain_side": side,
        "pain_severity": severity,
        "pain_trend": trend,
        "pain_timing": "after",
    }


def episodes_for(reports, today=TODAY):
    ids = {f"a{i}": day for i, (_, day) in enumerate(reports)}
    data = {f"a{i}": fb for i, (fb, _) in enumerate(reports)}
    return build_episodes(data, ids, today=today)


def test_no_pain_means_no_episodes():
    assert episodes_for([(feedback(pain=False), "2026-04-20")]) == []


def test_a_single_report_is_an_episode():
    episodes = episodes_for([(feedback(severity=6), "2026-04-20")])

    assert len(episodes) == 1
    episode = episodes[0]
    assert episode["location"] == "quad"
    assert episode["side"] == "left"
    assert episode["reports"] == 1
    assert episode["max_severity"] == 6
    assert episode["first_date"] == episode["last_date"] == "2026-04-20"


def test_reports_close_together_form_one_episode():
    episodes = episodes_for(
        [
            (feedback(severity=4), "2026-04-01"),
            (feedback(severity=7), "2026-04-10"),
            (feedback(severity=3), "2026-04-20"),
        ]
    )

    assert len(episodes) == 1
    assert episodes[0]["reports"] == 3
    assert episodes[0]["max_severity"] == 7
    assert episodes[0]["first_date"] == "2026-04-01"
    assert episodes[0]["last_date"] == "2026-04-20"


def test_reports_far_apart_split_into_episodes():
    gap = INJURY_EPISODE_GAP_DAYS + 1
    episodes = episodes_for(
        [
            (feedback(), "2026-03-01"),
            (feedback(), f"2026-03-{1 + gap:02d}"),
        ]
    )

    assert len(episodes) == 2


def test_different_locations_are_different_episodes():
    episodes = episodes_for(
        [
            (feedback(location="quad"), "2026-04-01"),
            (feedback(location="achilles"), "2026-04-02"),
        ]
    )

    assert {e["location"] for e in episodes} == {"quad", "achilles"}


def test_sides_are_tracked_separately():
    episodes = episodes_for(
        [
            (feedback(side="left"), "2026-04-01"),
            (feedback(side="right"), "2026-04-02"),
        ]
    )

    assert {e["side"] for e in episodes} == {"left", "right"}


def test_episodes_are_active_only_recently():
    recent = episodes_for([(feedback(), "2026-04-25")], today=TODAY)
    old = episodes_for(
        [(feedback(), f"2026-03-{1:02d}")],
        today=date(2026, 3, 1 + INJURY_ACTIVE_DAYS + 1),
    )

    assert recent[0]["active"] is True
    assert old[0]["active"] is False


def test_reports_without_a_date_are_ignored():
    episodes = build_episodes({"a": feedback()}, {}, today=TODAY)

    assert episodes == []


def test_only_lower_limb_locations_are_marked_explainable():
    episodes = episodes_for(
        [
            (feedback(location="other"), "2026-04-01"),
            (feedback(location="knee"), "2026-04-02"),
        ]
    )

    by_location = {e["location"]: e for e in episodes}
    assert by_location["other"]["explainable"] is False
    assert by_location["knee"]["explainable"] is True


# ---------------------------------------------------------------------------
# Correlation with sessions
# ---------------------------------------------------------------------------
def session(day, rpe=8, exercises=("Leg press",), status="completed", sid=1):
    return {
        "id": sid,
        "date": day,
        "kind": "strength",
        "title": "Legs",
        "rpe": rpe,
        "status": status,
        "exercises": [{"name": name} for name in exercises],
    }


def test_a_hard_leg_session_before_knee_pain_is_linked():
    episodes = episodes_for([(feedback(location="knee"), "2026-04-10")])

    result = link_sessions_to_episodes(
        episodes, [session("2026-04-09", exercises=("Leg press", "Leg extension"))]
    )

    assert len(result["links"]) == 1
    link = result["links"][0]
    assert link["location"] == "knee"
    assert link["session_date"] == "2026-04-09"
    assert "Leg press" in link["exercises"]
    assert "quads" in link["matched_muscles"]
    assert result["summary"]["episodes_with_hard_session"] == 1


def test_a_low_rpe_session_is_ignored():
    episodes = episodes_for([(feedback(location="knee"), "2026-04-10")])

    result = link_sessions_to_episodes(episodes, [session("2026-04-09", rpe=4)])

    assert result["links"] == []


def test_unrelated_exercises_are_ignored():
    episodes = episodes_for([(feedback(location="knee"), "2026-04-10")])

    result = link_sessions_to_episodes(
        episodes, [session("2026-04-09", exercises=("Bench press",))]
    )

    assert result["links"] == []


def test_sessions_without_recorded_exercises_cannot_be_linked():
    episodes = episodes_for([(feedback(location="knee"), "2026-04-10")])

    result = link_sessions_to_episodes(episodes, [session("2026-04-09", exercises=())])

    assert result["links"] == []


def test_sessions_outside_the_lookback_window_are_ignored():
    episodes = episodes_for([(feedback(location="knee"), "2026-04-20")])

    result = link_sessions_to_episodes(episodes, [session("2026-04-01")])

    assert result["links"] == []


def test_a_session_after_the_pain_cannot_explain_it():
    episodes = episodes_for([(feedback(location="knee"), "2026-04-20")])

    result = link_sessions_to_episodes(episodes, [session("2026-04-21")])

    assert result["links"] == []


def test_skipped_sessions_are_ignored():
    episodes = episodes_for([(feedback(location="knee"), "2026-04-10")])

    result = link_sessions_to_episodes(
        episodes, [session("2026-04-09", status="skipped")]
    )

    assert result["links"] == []


def test_upper_body_pain_is_not_linked_to_leg_work():
    episodes = episodes_for([(feedback(location="back"), "2026-04-10")])

    result = link_sessions_to_episodes(episodes, [session("2026-04-09")])

    # "back" is not a lower-limb location: the engine does not guess.
    assert result["links"] == []
