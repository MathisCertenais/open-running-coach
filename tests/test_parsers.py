"""Tests for the parser layer, driven by a synthetic OpenTracks KMZ.

The fixture reproduces real-file quirks (multiple tracks, an IDLE sample, no
heart rate) without containing any personal data.
"""

from __future__ import annotations

import pytest

from app.parsers import parse_file
from tests.fixtures.make_kmz import (
    DESCRIPTION,
    DOC_NAME,
    LAPS,
    TRACK_ID,
    write_synthetic_kmz,
)

EXPECTED_POINTS = sum(lap["points"] for lap in LAPS)


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
    assert len(activity.segments) == len(LAPS)
    assert len(activity.points) == EXPECTED_POINTS
    assert [len(seg) for seg in activity.segments] == [lap["points"] for lap in LAPS]


def test_reads_the_speed_array(activity):
    first = activity.points[0]

    assert first.speed == pytest.approx(LAPS[0]["speed"])
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


def test_start_time_comes_from_the_first_timestamp(activity):
    assert activity.start_time is not None
    assert activity.end_time > activity.start_time


def test_a_non_zip_file_is_rejected(tmp_path):
    broken = tmp_path / "broken.kmz"
    broken.write_bytes(b"this is not a zip archive")

    assert parse_file(broken) is None


def test_an_unsupported_extension_is_ignored(tmp_path):
    unknown = tmp_path / "activity.fit"
    unknown.write_text("irrelevant")

    assert parse_file(unknown) is None
