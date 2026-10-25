"""Race-day pacing plan built from a course GPX.

The plan holds a **constant effort**, not a constant pace: uphill kilometres are
slower and downhill ones faster, so the athlete arrives at the top of the climb
with the legs the plan assumed. The conversion uses the same Minetti (2002)
grade correction as GAP, which means the plan and the analysis tell the same
story.

No dependency is added: the route is read with ElementTree and the split is
solved in closed form.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

from .analysis import gap_factor
from .parsers.model import _local

EARTH_RADIUS_M = 6_371_000.0


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def read_route(path: Path) -> list[tuple[float, float, float | None]]:
    """Read a course as ``(lat, lon, ele)`` from a track or a route GPX.

    Both shapes occur in the wild: devices write ``<trkpt>`` for a recorded
    track, and race organisers usually publish ``<rtept>``. Neither carries
    timestamps, which is why this does not go through the activity parser.
    """
    root = ET.parse(path).getroot()
    points: list[tuple[float, float, float | None]] = []
    for element in root.iter():
        if _local(element.tag) not in ("trkpt", "rtept"):
            continue
        lat, lon = element.get("lat"), element.get("lon")
        if lat is None or lon is None:
            continue
        elevation = None
        for child in element:
            if _local(child.tag) == "ele" and child.text:
                try:
                    elevation = float(child.text)
                except ValueError:
                    elevation = None
                break
        points.append((float(lat), float(lon), elevation))
    return points


def _smooth_elevations(
    values: list[float | None], window: int = 5
) -> list[float | None]:
    """Forward-fill and average, tolerating missing elevations."""
    filled: list[float | None] = []
    last = None
    for value in values:
        if value is not None:
            last = value
        filled.append(last)
    if not filled or all(v is None for v in filled):
        return [None] * len(values)

    half = window // 2
    out: list[float | None] = []
    for i in range(len(filled)):
        if filled[i] is None:
            out.append(None)
            continue
        lo, hi = max(0, i - half), min(len(filled), i + half + 1)
        window_values = [v for v in filled[lo:hi] if v is not None]
        out.append(sum(window_values) / len(window_values) if window_values else None)
    return out


def _segments(
    points: list[tuple[float, float, float | None]], step_m: float
) -> list[dict]:
    """Merge raw points into segments of roughly ``step_m`` metres."""
    raw_elevations = [p[2] for p in points]
    spacings = sorted(
        _haversine(a[0], a[1], b[0], b[1]) for a, b in zip(points, points[1:])
    )
    # A recorded track has points every few metres and needs smoothing; a
    # published route is already decimated, and averaging it would shave the
    # ends of the course and under-report the climb.
    median_spacing = spacings[len(spacings) // 2] if spacings else 0.0
    elevations = (
        _smooth_elevations(raw_elevations) if median_spacing <= 30 else raw_elevations
    )
    segments: list[dict] = []

    start = 0
    distance = 0.0
    for index in range(1, len(points)):
        previous, current = points[index - 1], points[index]
        distance += _haversine(previous[0], previous[1], current[0], current[1])
        if distance < step_m and index != len(points) - 1:
            continue
        if distance <= 0:
            start = index
            continue

        ele_from, ele_to = elevations[start], elevations[index]
        gain = 0.0
        if ele_from is not None and ele_to is not None and ele_to > ele_from:
            gain = ele_to - ele_from
        grade = None
        if ele_from is not None and ele_to is not None:
            grade = (ele_to - ele_from) / distance

        segments.append(
            {
                "distance_m": distance,
                "grade": grade,
                "gain_m": gain,
                "net_m": (ele_to - ele_from)
                if ele_from is not None and ele_to is not None
                else 0.0,
            }
        )
        start = index
        distance = 0.0
    return segments


def _km_splits(segments: list[dict], times: list[float]) -> list[dict]:
    """Aggregate segments into per-kilometre splits.

    Positions are tracked in absolute distance, so a segment straddling a
    kilometre boundary contributes proportionally to both and nothing is
    counted twice.
    """
    splits: list[dict] = []
    km = 1
    cumulative_d = 0.0
    bucket_d = bucket_t = bucket_gain = bucket_net = 0.0

    def emit(partial: bool = False) -> None:
        nonlocal km, bucket_d, bucket_t, bucket_gain, bucket_net
        splits.append(
            {
                "km": km,
                "distance_m": round(bucket_d),
                "split_time_s": round(bucket_t, 1),
                "cumulative_time_s": 0.0,
                "elevation_gain_m": round(bucket_gain),
                "net_elevation_m": round(bucket_net),
                "grade_pct": round(bucket_net / bucket_d * 100, 1) if bucket_d else 0.0,
                "pace_s_per_km": round(bucket_t / (bucket_d / 1000.0), 1)
                if bucket_d
                else 0.0,
                **({"partial": True} if partial else {}),
            }
        )
        km += 1
        bucket_d = bucket_t = bucket_gain = bucket_net = 0.0

    for segment, seconds in zip(segments, times):
        length = segment["distance_m"]
        if length <= 0:
            continue
        position = 0.0
        while position < length - 1e-9:
            space = km * 1000.0 - (cumulative_d + position)
            take = min(length - position, space)
            share = take / length
            bucket_d += take
            bucket_t += seconds * share
            bucket_gain += segment["gain_m"] * share
            bucket_net += segment["net_m"] * share
            position += take
            if abs(km * 1000.0 - (cumulative_d + position)) < 1e-6:
                emit()
        cumulative_d += length

    if bucket_d > 1e-6:
        emit(partial=True)

    cumulative = 0.0
    for split in splits:
        cumulative += split["split_time_s"]
        split["cumulative_time_s"] = round(cumulative, 1)
    return splits


def build_plan(
    points: list[tuple[float, float, float | None]],
    target_time_s: float,
    step_m: float = 200.0,
) -> dict:
    """Distribute ``target_time_s`` over the course at constant effort.

    A gradient factor above 1 means the same *effort* moves you more slowly, so
    the time for a segment is ``length × factor / v0``. With
    ``s = Σ length_i × factor_i`` and ``v0 = s / target_time``, the total is
    exactly the target, by construction rather than by iteration.
    """
    if target_time_s <= 0:
        raise ValueError("Target time must be positive")
    segments = _segments(points, step_m)
    if not segments:
        raise ValueError("The course has no distance")

    factors = [gap_factor(segment["grade"]) for segment in segments]
    scaled = sum(
        segment["distance_m"] * factor for segment, factor in zip(segments, factors)
    )
    if scaled <= 0:
        raise ValueError("The course has no distance")

    flat_speed = scaled / target_time_s  # m/s on the flat, at this effort
    times = [
        segment["distance_m"] * factor / flat_speed
        for segment, factor in zip(segments, factors)
    ]
    total_distance = sum(segment["distance_m"] for segment in segments)
    total_gain = sum(segment["gain_m"] for segment in segments)
    splits = _km_splits(segments, times)

    return {
        "distance_m": round(total_distance),
        "elevation_gain_m": round(total_gain),
        "target_time_s": round(sum(times), 1),
        "average_pace_s_per_km": round(target_time_s / (total_distance / 1000.0), 1),
        "flat_equivalent_pace_s_per_km": round(1000.0 / flat_speed, 1),
        "splits": splits,
        "model": "constant effort, Minetti (2002) grade correction",
    }
