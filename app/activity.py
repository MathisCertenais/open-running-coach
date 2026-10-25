"""Basic activity statistics (distance, pace, elevation, ...)."""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Optional

from .config import MAX_MOVING_GAP, MOVING_SPEED_THRESHOLD
from .parsers import Activity, TrackPoint

# Mean Earth radius (meters)
_EARTH_RADIUS_M = 6371000.0

# Minimum elevation change (m) counted in elevation gain/loss
# (filters GPS altitude noise)
_ELEVATION_THRESHOLD_M = 1.0

# Implied speed (m/s) above which a GPS position jump is considered an error
# (e.g. 34 m between two nearly-simultaneous points).
MAX_IMPLIED_SPEED = 10.0


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in meters between two GPS coordinates (Haversine formula)."""
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * asin(sqrt(a))


def step_distance(a: TrackPoint, b: TrackPoint) -> float:
    """Robust distance between two consecutive GPS points.

    If the implied speed (distance / time) exceeds MAX_IMPLIED_SPEED, the
    position jump is treated as a GPS error: fall back to the distance
    integrated from the recorded speed (more reliable sensor).
    """
    d = haversine(a.lat, a.lon, b.lat, b.lon)
    dt = (b.time - a.time).total_seconds() if (a.time and b.time) else 0.0
    if dt > 0 and d / dt > MAX_IMPLIED_SPEED:
        sa, sb = a.speed, b.speed
        if sa is not None and sb is not None:
            sp = (sa + sb) / 2.0
        else:
            sp = sa if sa is not None else sb
        d = (sp * dt) if (sp is not None and sp > 0) else 0.0
    return d


def step_speed(a: TrackPoint, b: TrackPoint) -> float:
    """Effective speed (m/s) between two consecutive points.

    Uses the recorded sensor speed when present, otherwise falls back to the
    positional implied speed (distance / time). This lets formats without a
    speed array (e.g. Strava GPX) still compute moving time and pace.
    """
    d = step_distance(a, b)
    dt = (b.time - a.time).total_seconds() if (a.time and b.time) else 0.0
    implied = d / dt if dt > 0 else 0.0
    sa, sb = a.speed, b.speed
    if sa is not None and sb is not None:
        sensor = (sa + sb) / 2.0
    else:
        sensor = sa if sa is not None else sb
    if sensor is not None and sensor > 0:
        return sensor
    return implied


def is_moving_step(a: TrackPoint, b: TrackPoint) -> bool:
    """True if the step between two points counts as moving time."""
    if a.time is None or b.time is None:
        return False
    dt = (b.time - a.time).total_seconds()
    if not (0 < dt <= MAX_MOVING_GAP):
        return False
    return step_speed(a, b) >= MOVING_SPEED_THRESHOLD


def _smooth(values: list[float], window: int = 3) -> list[float]:
    """Smoothing by moving average (reduces GPS altitude noise)."""
    if not values:
        return []
    if window < 1 or len(values) < 3:
        return values[:]
    half = window // 2
    smoothed: list[float] = []
    for i in range(len(values)):
        lo = max(0, i - half)
        hi = min(len(values), i + half + 1)
        smoothed.append(sum(values[lo:hi]) / (hi - lo))
    return smoothed


def compute_stats(activity: Activity) -> dict:
    """Compute derived statistics for an activity."""
    pts = activity.points
    empty = {
        "distance_m": 0.0,
        "elapsed_time_s": 0.0,
        "moving_time_s": 0.0,
        "avg_speed_ms": 0.0,
        "avg_pace_s_per_km": 0.0,
        "elevation_gain_m": 0.0,
        "elevation_loss_m": 0.0,
        "min_elevation_m": None,
        "max_elevation_m": None,
        "max_speed_ms": None,
        "avg_hr": None,
        "max_hr": None,
        "avg_cadence": None,
        "has_hr": False,
        "has_cadence": False,
    }

    valid = [p for p in pts if p.lat is not None and p.lon is not None]
    if len(valid) < 2:
        if activity.start_time and activity.end_time:
            empty["elapsed_time_s"] = (activity.end_time - activity.start_time).total_seconds()
        return empty

    distance_m = 0.0
    moving_time_s = 0.0
    max_speed = 0.0
    hr_vals: list[float] = []
    cadence_vals: list[float] = []

    for i in range(1, len(pts)):
        a, b = pts[i - 1], pts[i]
        if not (a.lat is not None and b.lat is not None
                and a.lon is not None and b.lon is not None):
            continue
        distance_m += step_distance(a, b)
        spd = step_speed(a, b)
        if spd > max_speed:
            max_speed = spd
        if is_moving_step(a, b):
            moving_time_s += (b.time - a.time).total_seconds()

    for p in pts:
        if p.hr is not None and p.hr > 0:
            hr_vals.append(p.hr)
        if p.cadence is not None and p.cadence > 0:
            cadence_vals.append(p.cadence)

    # Elevation on smoothed altitude
    elevations = [p.ele for p in valid if p.ele is not None]
    gain = loss = 0.0
    if len(elevations) >= 2:
        smoothed = _smooth(elevations, window=5)
        for i in range(1, len(smoothed)):
            d = smoothed[i] - smoothed[i - 1]
            if abs(d) < _ELEVATION_THRESHOLD_M:
                continue
            if d > 0:
                gain += d
            else:
                loss += -d

    elapsed = 0.0
    if activity.start_time and activity.end_time:
        elapsed = max(0.0, (activity.end_time - activity.start_time).total_seconds())

    avg_speed = distance_m / moving_time_s if moving_time_s > 0 else 0.0
    avg_pace = moving_time_s / (distance_m / 1000.0) if distance_m > 0 else 0.0

    return {
        "distance_m": round(distance_m, 1),
        "elapsed_time_s": round(elapsed, 1),
        "moving_time_s": round(moving_time_s, 1),
        "avg_speed_ms": round(avg_speed, 2),
        "avg_pace_s_per_km": round(avg_pace, 1),
        "elevation_gain_m": round(gain, 1),
        "elevation_loss_m": round(loss, 1),
        "min_elevation_m": round(min(elevations), 1) if elevations else None,
        "max_elevation_m": round(max(elevations), 1) if elevations else None,
        "max_speed_ms": round(max_speed, 2) if max_speed > 0 else None,
        "avg_hr": round(sum(hr_vals) / len(hr_vals)) if hr_vals else None,
        "max_hr": max(hr_vals) if hr_vals else None,
        "avg_cadence": round(sum(cadence_vals) / len(cadence_vals), 1) if cadence_vals else None,
        "has_hr": bool(hr_vals),
        "has_cadence": bool(cadence_vals),
    }


def to_summary(activity: Activity, note: str, stats: dict) -> dict:
    """Serialize an Activity (light summary) for the API."""
    return {
        "id": activity.id,
        "filename": activity.filename,
        "name": activity.name,
        "description": activity.description,
        "note": note,
        "has_note": bool(note),
        "activity_type": activity.activity_type,
        "activity_type_raw": activity.activity_type_raw,
        "start_time": activity.start_time.isoformat() if activity.start_time else None,
        "end_time": activity.end_time.isoformat() if activity.end_time else None,
        "points_count": len(activity.points),
        "segments": _count_segments(activity),
        "markers_count": len(activity.markers),
        "stats": stats,
    }


def to_detail(activity: Activity, note: str, stats: dict) -> dict:
    """Serialize a full Activity (with trackpoints for the map)."""
    summary = to_summary(activity, note, stats)
    points = []
    for p in activity.points:
        points.append([
            p.lat, p.lon, p.ele,
            p.time.isoformat() if p.time else None,
            p.speed, p.hr, p.cadence, p.ptype,
        ])
    markers = []
    for m in activity.markers:
        markers.append({
            "lat": m.lat,
            "lon": m.lon,
            "ele": m.ele,
            "name": m.name,
            "description": m.description,
            "time": m.time.isoformat() if m.time else None,
        })
    summary["points"] = points
    summary["markers"] = markers
    return summary


def _count_segments(activity: Activity) -> int:
    """Count the number of non-empty segments (laps)."""
    return sum(1 for seg in activity.segments if any(
        p.lat is not None and p.lon is not None for p in seg
    ))
