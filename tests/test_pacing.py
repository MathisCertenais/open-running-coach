"""Tests for the race-day pacing plan."""

from __future__ import annotations

import pytest

from app import pacing

FLAT_ROUTE = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <rte>
    <name>Flat 3 km</name>
    <rtept lat="48.8500" lon="2.3500"><ele>30</ele></rtept>
    <rtept lat="48.8590" lon="2.3500"><ele>30</ele></rtept>
    <rtept lat="48.8680" lon="2.3500"><ele>30</ele></rtept>
    <rtept lat="48.8770" lon="2.3500"><ele>30</ele></rtept>
  </rte>
</gpx>
"""

# Two flat kilometres, then a climb: with a fixed target time the flat part
# must come out faster than the climbing part.
CLIMB_ROUTE = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="48.8500" lon="2.3500"><ele>300</ele></trkpt>
    <trkpt lat="48.8590" lon="2.3500"><ele>300</ele></trkpt>
    <trkpt lat="48.8680" lon="2.3500"><ele>300</ele></trkpt>
    <trkpt lat="48.8770" lon="2.3500"><ele>420</ele></trkpt>
  </trkseg></trk>
</gpx>
"""


@pytest.fixture()
def flat(tmp_path):
    path = tmp_path / "flat.gpx"
    path.write_text(FLAT_ROUTE, encoding="utf-8")
    return path


@pytest.fixture()
def climb(tmp_path):
    path = tmp_path / "climb.gpx"
    path.write_text(CLIMB_ROUTE, encoding="utf-8")
    return path


def test_reads_a_route_gpx(flat):
    points = pacing.read_route(flat)

    assert len(points) == 4
    assert points[0][2] == 30.0


def test_reads_a_track_gpx(climb):
    points = pacing.read_route(climb)

    assert len(points) == 4
    assert points[-1][2] == 420.0


def test_reads_a_kmz_style_zip_is_not_supported_but_fails_cleanly(tmp_path):
    broken = tmp_path / "course.gpx"
    broken.write_bytes(b"not xml")

    with pytest.raises(Exception):
        pacing.read_route(broken)


def test_the_plan_hits_the_target_time(flat):
    plan = pacing.build_plan(pacing.read_route(flat), target_time_s=1080)

    assert plan["target_time_s"] == pytest.approx(1080, abs=1)
    assert sum(s["split_time_s"] for s in plan["splits"]) == pytest.approx(1080, abs=1)


def test_a_flat_course_has_almost_constant_pace(flat):
    plan = pacing.build_plan(pacing.read_route(flat), target_time_s=1080)

    paces = [s["pace_s_per_km"] for s in plan["splits"] if not s.get("partial")]
    assert max(paces) - min(paces) < 2


def test_the_climbing_split_is_slower_than_the_flat_ones(climb):
    plan = pacing.build_plan(pacing.read_route(climb), target_time_s=1800)

    paces = [s["pace_s_per_km"] for s in plan["splits"]]
    assert paces[-1] > paces[0]
    assert paces[-1] > paces[1]


def test_a_climb_costs_more_time_than_the_same_distance_flat(flat, climb):
    flat_plan = pacing.build_plan(pacing.read_route(flat), target_time_s=1800)
    climb_plan = pacing.build_plan(pacing.read_route(climb), target_time_s=1800)

    # Same target, same distance: the hilly plan must put more time into its
    # climbing kilometre than the flat plan spends on any kilometre.
    flat_pace = flat_plan["splits"][0]["pace_s_per_km"]
    climb_pace = climb_plan["splits"][-1]["pace_s_per_km"]
    assert climb_pace > flat_pace


def test_splits_are_contiguous_and_cumulative(climb):
    plan = pacing.build_plan(pacing.read_route(climb), target_time_s=1800)

    cumulative = 0.0
    for split in plan["splits"]:
        cumulative += split["split_time_s"]
        assert split["cumulative_time_s"] == pytest.approx(cumulative, abs=0.2)


def test_elevation_gain_is_reported(climb):
    plan = pacing.build_plan(pacing.read_route(climb), target_time_s=1800)

    assert plan["elevation_gain_m"] >= 115


def test_a_course_without_distance_is_rejected(tmp_path):
    path = tmp_path / "point.gpx"
    path.write_text(
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><rte>'
        '<rtept lat="48.85" lon="2.35"/></rte></gpx>',
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        pacing.build_plan(pacing.read_route(path), target_time_s=600)


def test_a_non_positive_target_is_rejected(flat):
    with pytest.raises(ValueError):
        pacing.build_plan(pacing.read_route(flat), target_time_s=0)
