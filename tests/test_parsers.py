"""Tests for the KMZ (OpenTracks) parser, driven by a synthetic fixture.

The fixture reproduces real-file quirks (three tracks, an isolated IDLE sample,
no heart rate) without containing any personal data.
"""

from __future__ import annotations

import pytest

from app.parsers import parse_file
from tests.fixtures.make_kmz import (
    DESCRIPTION,
    DOC_NAME,
    TRACK_ID,
    write_synthetic_kmz,
)
from tests.fixtures.track import LAPS, STEP_S

EXPECTED_POINTS = int(sum(duration for duration, _ in LAPS) / STEP_S)
EXPECTED_SEGMENTS = len(LAPS)


@pytest.fixture()
def activity(tmp_path):
    return parse_file(write_synthetic_kmz(tmp_path / "synthetic.kmz"))


def test_parses_the_document_metadata(activity):
    assert activity is not None
    assert activity.id == TRACK_ID
    assert activity.name == DOC_NAME
    assert activity.description == DESCRIPTION


def test_normalises_the_activity_type(activity):
    assert activity.activity_type_raw == "running"
    assert activity.activity_type == "running"


def test_keeps_one_segment_per_track(activity):
    assert len(activity.segments) == EXPECTED_SEGMENTS
    assert len(activity.points) == EXPECTED_POINTS
    assert [len(seg) for seg in activity.segments] == [
        int(duration / STEP_S) for duration, _ in LAPS
    ]


def test_reads_the_speed_array(activity):
    first = activity.points[0]

    assert first.speed == pytest.approx(LAPS[0][1], rel=1e-3)
    assert first.lat == pytest.approx(48.8566, abs=1e-6)
    assert first.lon == pytest.approx(2.3522, abs=1e-6)


def test_tolerates_a_missing_heart_rate_and_cadence(activity):
    # The OpenTracks schema declares both, but real exports omit them.
    assert all(p.hr is None for p in activity.points)
    assert all(p.cadence is None for p in activity.points)


def test_reads_the_trackpoint_types(activity):
    first_lap = activity.segments[0]

    assert first_lap[0].ptype == "SEGMENT_START_MANUAL"
    assert first_lap[-1].ptype == "IDLE"
    assert activity.segments[1][0].ptype == "SEGMENT_START_MANUAL"


def test_start_time_comes_from_the_first_timestamp(activity):
    assert activity.start_time is not None
    assert activity.end_time > activity.start_time


def test_moving_time_excludes_the_idle_sample(activity, tmp_path):
    from app.activity import compute_stats
    from tests.fixtures.make_kmz import write_kmz
    from tests.fixtures.track import build_run

    run = build_run(with_sensors=False)
    with_idle = compute_stats(parse_file(write_kmz(tmp_path / "idle.kmz", run)))
    without_idle = compute_stats(
        parse_file(write_kmz(tmp_path / "no-idle.kmz", run, mark_idle=False))
    )

    # The step that starts on the idle sample is excluded from moving time.
    assert without_idle["moving_time_s"] - with_idle["moving_time_s"] == pytest.approx(
        STEP_S, abs=0.01
    )
    # Distance is unaffected: the athlete still covered the ground.
    assert with_idle["distance_m"] == pytest.approx(
        without_idle["distance_m"], abs=0.01
    )


def test_a_non_zip_file_is_rejected(tmp_path):
    broken = tmp_path / "broken.kmz"
    broken.write_bytes(b"this is not a zip archive")

    assert parse_file(broken) is None


def test_a_zip_without_kml_is_rejected(tmp_path):
    import zipfile

    empty = tmp_path / "empty.kmz"
    with zipfile.ZipFile(empty, "w") as zf:
        zf.writestr("readme.txt", "no kml here")

    assert parse_file(empty) is None


def test_an_unsupported_extension_is_ignored(tmp_path):
    unknown = tmp_path / "activity.fit"
    unknown.write_text("irrelevant")

    assert parse_file(unknown) is None
