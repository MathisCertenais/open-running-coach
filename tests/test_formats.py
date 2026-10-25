"""Cross-format tests: the same run, exported by three different tools.

GPX (Strava shape), TCX (Garmin shape) and KMZ (OpenTracks shape) carry the same
positions, timestamps and speeds, so every statistic must agree. This is the
test that catches a parser drifting away from the shared ``Activity`` model.
"""

from __future__ import annotations

import pytest

from app.activity import compute_stats
from app.analysis import compute_gap, compute_pace_zones
from app.parsers import parse_file
from tests.fixtures.make_gpx import write_gpx
from tests.fixtures.make_kmz import write_kmz
from tests.fixtures.make_tcx import write_tcx
from tests.fixtures.track import LAPS, STEP_S, build_run

EXPECTED_SEGMENTS = len(LAPS)
EXPECTED_POINTS = int(sum(duration for duration, _ in LAPS) / STEP_S)


@pytest.fixture(scope="module")
def parsed(tmp_path_factory):
    directory = tmp_path_factory.mktemp("formats")
    run = build_run()
    return {
        "gpx": parse_file(write_gpx(directory / "run.gpx", run)),
        "tcx": parse_file(write_tcx(directory / "run.tcx", run)),
        "kmz": parse_file(write_kmz(directory / "run.kmz", run, mark_idle=False)),
    }


def test_every_format_parses(parsed):
    for name, activity in parsed.items():
        assert activity is not None, name
        assert len(activity.points) == EXPECTED_POINTS, name
        assert len(activity.segments) == EXPECTED_SEGMENTS, name


def test_activity_type_is_running_in_every_format(parsed):
    for name, activity in parsed.items():
        assert activity.activity_type == "running", name


def test_distance_agrees_across_formats(parsed):
    distances = {name: compute_stats(a)["distance_m"] for name, a in parsed.items()}

    assert max(distances.values()) - min(distances.values()) < 1.0, distances
    # 300 s at 2.5 m/s, 300 s at 3.33 m/s, 120 s at 4 m/s, plus lap transitions.
    assert distances["gpx"] == pytest.approx(2235, abs=15)


def test_moving_time_agrees_across_formats(parsed):
    moving = {name: compute_stats(a)["moving_time_s"] for name, a in parsed.items()}

    assert max(moving.values()) - min(moving.values()) < 2.0, moving
    assert moving["gpx"] == pytest.approx(EXPECTED_POINTS - 1, abs=2)


def test_pace_zones_agree_across_formats(parsed):
    zones = {name: compute_pace_zones(a.points)["zones"] for name, a in parsed.items()}

    for index in range(6):
        times = [z[index]["time_s"] for z in zones.values()]
        assert max(times) - min(times) < 2.0, (index, times)

    # One lap in Z1, one in Z3, one in Z5.
    assert zones["gpx"][0]["time_s"] == pytest.approx(299, abs=3)
    assert zones["gpx"][2]["time_s"] == pytest.approx(299, abs=3)
    assert zones["gpx"][4]["time_s"] == pytest.approx(119, abs=3)


def test_gap_agrees_across_formats(parsed):
    gaps = {
        name: compute_gap(a.points)["gap_pace_s_per_km"] for name, a in parsed.items()
    }

    assert max(gaps.values()) - min(gaps.values()) < 2.0, gaps
    # A 2% climb makes grade-adjusted pace faster than the raw pace.
    assert gaps["gpx"] < 1000 / (2235 / (EXPECTED_POINTS - 1))


def test_heart_rate_is_read_only_where_the_format_has_it(parsed):
    assert any(p.hr is not None for p in parsed["gpx"].points)
    assert any(p.hr is not None for p in parsed["tcx"].points)
    # OpenTracks exports omit heart rate entirely: see the data-quirk contract.
    assert all(p.hr is None for p in parsed["kmz"].points)


def test_speed_is_absent_from_gpx_and_derived_from_positions(parsed):
    assert all(p.speed is None for p in parsed["gpx"].points)
    assert all(p.speed is not None for p in parsed["kmz"].points)
    assert all(p.speed is not None for p in parsed["tcx"].points)


@pytest.mark.parametrize(
    "strava_code, expected",
    [("9", "running"), ("12", "trail_running"), ("1", "unknown")],
)
def test_strava_activity_codes_are_mapped(tmp_path, strava_code, expected):
    activity = parse_file(
        write_gpx(tmp_path / "run.gpx", build_run(), strava_type=strava_code)
    )

    assert activity.activity_type == expected


@pytest.mark.parametrize(
    "sport, expected",
    [("Running", "running"), ("TrailRunning", "trail_running")],
)
def test_garmin_sports_are_mapped(tmp_path, sport, expected):
    activity = parse_file(write_tcx(tmp_path / "run.tcx", build_run(), sport=sport))

    assert activity.activity_type == expected


def test_an_invalid_gpx_is_rejected(tmp_path):
    broken = tmp_path / "broken.gpx"
    broken.write_text("<gpx><trk>", encoding="utf-8")  # truncated XML

    assert parse_file(broken) is None


def test_an_invalid_tcx_is_rejected(tmp_path):
    broken = tmp_path / "broken.tcx"
    broken.write_text("<TrainingCenterDatabase>", encoding="utf-8")

    assert parse_file(broken) is None


def test_a_gpx_without_track_points_is_rejected(tmp_path):
    empty = tmp_path / "empty.gpx"
    empty.write_text(
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk/></gpx>',
        encoding="utf-8",
    )

    assert parse_file(empty) is None
