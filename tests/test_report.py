"""Tests for the coach/physio export (Markdown and print HTML)."""
from __future__ import annotations

from app import report

DATA = {
    "profile": {"name": "Mathis"},
    "totals": {
        "activities": 12,
        "distance_m": 84_000,
        "moving_time_s": 25_200,
        "elevation_gain_m": 640,
    },
    "window": {"start": "2026-01-01", "end": "2026-03-01"},
    "load": {"ctl": 42.0, "atl": 38.0, "tsb": 4.0, "form": "neutral"},
    "intensity": {
        "easy": {"time_pct": 82.0},
        "moderate": {"time_pct": 9.0},
        "hard": {"time_pct": 9.0},
    },
    "injuries": {
        "episodes": [
            {
                "location": "knee",
                "side": "left",
                "first_date": "2026-02-10",
                "last_date": "2026-02-12",
                "reports": 2,
                "max_severity": 6,
                "verdict": "plausible",
            }
        ],
        "links": [
            {
                "location": "knee",
                "side": "left",
                "pain_first_date": "2026-02-10",
                "session_title": "Lower body",
                "session_date": "2026-02-09",
                "session_rpe": 8,
                "hours_before": 24,
                "explanation": "Leg press loads quads",
            }
        ],
        "summary": {
            "observed_rate": 1.0,
            "base_rate": 0.3,
            "reading": "more often than your usual weeks",
        },
    },
    "sessions": [
        {
            "date": "2026-02-09",
            "title": "Lower body",
            "kind": "strength",
            "rpe": 8,
            "exercises": [{"name": "Leg press"}],
        }
    ],
    "shoes": [
        {"name": "Brooks Ghost Trail", "distance_m": 100_000, "threshold_km": 1000}
    ],
}


def test_markdown_has_the_sections_a_coach_needs():
    text = report.markdown(report.build(DATA))

    assert "# Training report — Mathis" in text
    assert "## Summary" in text
    assert "## Load" in text
    assert "## Intensity distribution" in text
    assert "## Injury watch" in text
    assert "lower body" in text.lower()
    assert "Leg press" in text
    assert "Correlation is not causation" in text


def test_markdown_reports_the_base_rate_next_to_the_observed_rate():
    text = report.markdown(report.build(DATA))

    assert "100%" in text
    assert "30%" in text


def test_html_is_self_contained_and_printable():
    page = report.html(report.build(DATA))

    assert page.startswith("<!DOCTYPE html>")
    assert "window.print()" in page
    assert "@media print" in page
    assert "Leg press" in page


def test_an_empty_dataset_still_renders():
    empty = report.build({"profile": {}})

    assert "No pain reported." in report.markdown(empty)
    assert "No shoes recorded." in report.markdown(empty)
    assert "<html" in report.html(empty)
