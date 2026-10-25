"""The canonical synthetic run, rendered into every supported data format.

One definition keeps the cross-format tests honest: the same positions,
timestamps, speeds and elevation go into a GPX (Strava shape), a TCX (Garmin
shape) and a KMZ (OpenTracks shape), so the three parsers must produce the same
statistics. Nothing here is derived from real activity data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# Same sphere as app.activity.haversine, so positions measure back to the
# intended distance exactly.
EARTH_RADIUS_M = 6_371_000.0
M_PER_DEG_LAT = 2 * math.pi * EARTH_RADIUS_M / 360

LAT0, LON0 = 48.8566, 2.3522
START = datetime(2026, 4, 12, 7, 30, tzinfo=timezone.utc)

# (duration_s, speed_m_s): recovery, tempo, then VO2max. Three laps.
LAPS: tuple[tuple[float, float], ...] = (
    (300.0, 1000.0 / 400),  # Z1
    (300.0, 1000.0 / 300),  # Z3
    (120.0, 1000.0 / 250),  # Z5
)
STEP_S = 1.0
CLIMB = 0.02  # 2% average gradient, so GAP has something to correct


@dataclass(frozen=True)
class Sample:
    """One track point, with every field a format might carry."""

    t: datetime
    lat: float
    lon: float
    ele: float
    speed: float
    hr: float | None = None
    cadence: float | None = None
    ptype: str = "TRACKPOINT"


@dataclass
class Run:
    """A run split into laps."""

    segments: list[list[Sample]] = field(default_factory=list)

    @property
    def samples(self) -> list[Sample]:
        return [s for segment in self.segments for s in segment]

    @property
    def start(self) -> datetime:
        return self.segments[0][0].t

    @property
    def duration_s(self) -> float:
        points = self.samples
        return (points[-1].t - points[0].t).total_seconds()

    @property
    def distance_m(self) -> float:
        """Planned distance: sum of duration x speed per lap."""
        return sum(len(seg) * seg[0].speed * STEP_S for seg in self.segments)


def build_run(
    laps: tuple[tuple[float, float], ...] = LAPS,
    start: datetime = START,
    step_s: float = STEP_S,
    with_sensors: bool = True,
) -> Run:
    """Build the canonical run, lap by lap, heading east on a steady climb.

    ``with_sensors=False`` omits heart rate and cadence, reproducing the current
    OpenTracks exports where both fields are declared but absent.
    """
    segments: list[list[Sample]] = []
    t = start
    lat, lon = LAT0, LON0
    distance = 0.0

    for duration, speed in laps:
        n = max(1, int(round(duration / step_s)))
        dt = duration / n
        segment: list[Sample] = []
        for i in range(n):
            fraction = i / max(1, n - 1)
            segment.append(
                Sample(
                    t=t,
                    lat=lat,
                    lon=lon,
                    ele=30.0 + CLIMB * distance,
                    speed=speed,
                    hr=140.0 + 20.0 * fraction if with_sensors else None,
                    cadence=80.0 + 6.0 * fraction if with_sensors else None,
                )
            )
            step = speed * dt
            lon += step / (M_PER_DEG_LAT * math.cos(math.radians(lat)))
            distance += step
            t += timedelta(seconds=dt)
        segments.append(segment)

    return Run(segments=segments)


def iso(dt: datetime) -> str:
    """Format a timestamp the way every exporter does (UTC, Z suffix)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
