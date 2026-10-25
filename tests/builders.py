"""Synthetic data builders shared by the test suite.

No real activity data is ever committed. Every point, timestamp and coordinate
here is generated from the constants below, so the suite stays reproducible and
contains nothing personal.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

from app.parsers import Activity, TrackPoint

# Arbitrary starting point (Paris); the location itself is irrelevant.
LAT0 = 48.8566
LON0 = 2.3522
M_PER_DEG_LAT = 111_320.0

# A fixed reference date so tests never depend on the wall clock.
START = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)


def speed_for_pace(pace_s_per_km: float) -> float:
    """Convert a pace in seconds per kilometre to metres per second."""
    return 1000.0 / pace_s_per_km


def make_points(
    segments: Sequence[tuple[float, float]],
    start: datetime = START,
    step_s: float = 1.0,
    lat: float = LAT0,
    lon: float = LON0,
) -> list[TrackPoint]:
    """Build a track from ``(duration_s, speed_m_s)`` segments.

    Points advance due east so the recorded speed sensor and the positional
    implied speed agree, which is what real OpenTracks files look like.
    """
    t = start
    points = [TrackPoint(lat=lat, lon=lon, time=t, speed=segments[0][1])]
    for duration, speed in segments:
        n = max(1, int(round(duration / step_s)))
        dt = duration / n
        for _ in range(n):
            d = speed * dt
            lon += d / (M_PER_DEG_LAT * math.cos(math.radians(lat)))
            t += timedelta(seconds=dt)
            points.append(TrackPoint(lat=lat, lon=lon, time=t, speed=speed))
    return points


def make_activity(
    points: Iterable[TrackPoint],
    activity_id: str = "test-activity",
    name: str = "Test activity",
    description: str | None = None,
    activity_type: str = "running",
    activity_type_raw: str = "running",
) -> Activity:
    """Wrap a point list into an Activity the analytics can consume."""
    pts = list(points)
    return Activity(
        id=activity_id,
        filename=f"{activity_id}.kmz",
        name=name,
        description=description,
        activity_type=activity_type,
        activity_type_raw=activity_type_raw,
        points=pts,
        segments=[pts],
        markers=[],
    )


def daily_activity(
    day: datetime,
    rpe: int = 5,
    duration_s: float = 3600.0,
    step_s: float = 60.0,
    activity_id: str | None = None,
) -> Activity:
    """A one-hour steady run on a given day.

    With ``rpe=5`` and a 60-minute moving time the session-RPE load is exactly
    300, which makes load-model assertions easy to read.
    """
    points = make_points(
        [(duration_s, speed_for_pace(300))],
        start=day,
        step_s=step_s,
    )
    return make_activity(
        points, activity_id=activity_id or f"run-{day.date().isoformat()}"
    )
