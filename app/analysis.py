"""Advanced activity analysis: splits, laps, pace zones, GAP, records,
matched-route detection, and monthly statistics.
"""
from __future__ import annotations

from bisect import bisect_left
from typing import Optional

from .activity import compute_stats, is_moving_step, step_distance, step_speed
from .config import (
    BEST_EFFORT_DISTANCES,
    GAP_DOWNHILL_FACTOR,
    GAP_MAX_DOWN_GRADE,
    GAP_UPHILL_FACTOR,
    MATCH_CELL_DEG,
    MATCH_DISTANCE_RATIO,
    MATCH_JACCARD_THRESHOLD,
    MAX_MOVING_GAP,
    PACE_ZONES,
)
from .parsers import Activity, TrackPoint

def _is_moving(a: TrackPoint, b: TrackPoint) -> bool:
    return is_moving_step(a, b)


def _smooth_altitudes(values: list[Optional[float]], window: int = 5) -> list[Optional[float]]:
    """Moving-average smoothing that tolerates missing (None) altitudes."""
    if not values:
        return []
    # Forward-fill gaps
    filled: list[Optional[float]] = []
    last: Optional[float] = None
    for v in values:
        if v is not None:
            last = v
        filled.append(last)

    half = window // 2
    result: list[Optional[float]] = []
    for i in range(len(filled)):
        if filled[i] is None:
            result.append(None)
            continue
        lo = max(0, i - half)
        hi = min(len(filled), i + half + 1)
        vals = [filled[j] for j in range(lo, hi) if filled[j] is not None]
        result.append(sum(vals) / len(vals) if vals else None)
    return result


def _steps(points: list[TrackPoint]) -> list[dict]:
    """Steps between consecutive valid GPS points.

    Each step holds the distance, time (elapsed / moving), grade (computed on
    smoothed altitude) and elevation gain. Points without coordinates are
    skipped.
    """
    valid = [p for p in points if p.lat is not None and p.lon is not None]
    if len(valid) < 2:
        return []

    altitudes = _smooth_altitudes([p.ele for p in valid], window=5)

    steps: list[dict] = []
    for i in range(1, len(valid)):
        a, b = valid[i - 1], valid[i]
        d = step_distance(a, b)
        dt = (b.time - a.time).total_seconds() if (a.time and b.time) else 0.0
        moving = _is_moving(a, b) and 0 < dt <= MAX_MOVING_GAP

        ea, eb = altitudes[i - 1], altitudes[i]
        grade = None
        gain = 0.0
        if ea is not None and eb is not None and d > 0:
            grade = (eb - ea) / d
            if eb > ea:
                gain = eb - ea

        speed = step_speed(a, b)

        steps.append({
            "d": d,
            "dt": dt,
            "dt_moving": dt if moving else 0.0,
            "grade": grade,
            "speed": speed,
            "gain": gain,
        })
    return steps


# ---------------------------------------------------------------------------
# Splits (per km)
# ---------------------------------------------------------------------------
def compute_splits(points: list[TrackPoint], split_m: float = 1000.0) -> list[dict]:
    steps = _steps(points)
    splits: list[dict] = []
    if not steps:
        return splits

    d = m = e = g = 0.0
    boundary = split_m

    def _emit() -> dict:
        pace = m / (d / 1000.0) if d > 0 else 0.0
        return {
            "index": len(splits) + 1,
            "distance_m": round(d, 1),
            "moving_time_s": round(m, 1),
            "elapsed_time_s": round(e, 1),
            "pace_s_per_km": round(pace, 1),
            "elevation_gain_m": round(g, 1),
        }

    for st in steps:
        d += st["d"]
        m += st["dt_moving"]
        e += st["dt"]
        g += st["gain"]
        if d >= boundary:
            splits.append(_emit())
            d = m = e = g = 0.0

    if d > 0:
        splits.append(_emit())

    return splits


# ---------------------------------------------------------------------------
# Laps (manual segments = <Track>)
# ---------------------------------------------------------------------------
def compute_laps(activity: Activity) -> list[dict]:
    laps: list[dict] = []
    for i, seg in enumerate(activity.segments):
        stats = compute_stats(_segment_as_activity(activity, seg))
        if stats["distance_m"] < 5:
            continue  # empty or too-short segment
        laps.append({
            "index": i + 1,
            "start_time": seg[0].time.isoformat() if seg and seg[0].time else None,
            "distance_m": stats["distance_m"],
            "moving_time_s": stats["moving_time_s"],
            "elapsed_time_s": stats["elapsed_time_s"],
            "pace_s_per_km": stats["avg_pace_s_per_km"],
            "elevation_gain_m": stats["elevation_gain_m"],
            "avg_hr": stats["avg_hr"],
        })
    return laps


def _segment_as_activity(activity: Activity, seg: list[TrackPoint]) -> Activity:
    """Build a dummy Activity from a segment (to reuse compute_stats)."""
    return Activity(
        id=activity.id,
        filename=activity.filename,
        name=activity.name,
        description=activity.description,
        activity_type=activity.activity_type,
        activity_type_raw=activity.activity_type_raw,
        points=seg,
        segments=[seg],
        markers=[],
    )


# ---------------------------------------------------------------------------
# Pace zones
# ---------------------------------------------------------------------------
def compute_pace_zones(points: list[TrackPoint]) -> dict:
    steps = _steps(points)
    zones = [{"name": z["name"], "color": z["color"], "min": z["min"], "max": z["max"],
              "time_s": 0.0, "distance_m": 0.0} for z in PACE_ZONES]
    total_time = 0.0
    total_distance = 0.0

    for st in steps:
        if not st["dt_moving"] or st["speed"] is None or st["speed"] <= 0:
            continue
        pace = 1000.0 / st["speed"]  # s/km
        zi = _zone_index(pace)
        if zi is None:
            continue
        zones[zi]["time_s"] += st["dt_moving"]
        zones[zi]["distance_m"] += st["d"]
        total_time += st["dt_moving"]
        total_distance += st["d"]

    for z in zones:
        z["time_s"] = round(z["time_s"], 1)
        z["distance_m"] = round(z["distance_m"], 1)
        z["percent"] = round(100.0 * z["time_s"] / total_time, 1) if total_time > 0 else 0.0

    return {
        "zones": zones,
        "total_time_s": round(total_time, 1),
        "total_distance_m": round(total_distance, 1),
    }


def _zone_index(pace_s_per_km: float) -> Optional[int]:
    for i, z in enumerate(PACE_ZONES):
        mn, mx = z["min"], z["max"]
        if (mn is None or pace_s_per_km >= mn) and (mx is None or pace_s_per_km < mx):
            return i
    return None


# ---------------------------------------------------------------------------
# GAP (Grade-Adjusted Pace)
# ---------------------------------------------------------------------------
def _gap_factor(grade: Optional[float]) -> float:
    if grade is None or grade == 0:
        return 1.0
    if grade > 0:
        return 1.0 + GAP_UPHILL_FACTOR * grade
    g = max(grade, -GAP_MAX_DOWN_GRADE)
    return 1.0 + GAP_DOWNHILL_FACTOR * g  # g < 0 => factor < 1


def compute_gap(points: list[TrackPoint]) -> dict:
    steps = _steps(points)
    total_moving = 0.0
    gap_time = 0.0
    total_distance = 0.0
    grade_sum = 0.0
    grade_count = 0

    for st in steps:
        if not st["dt_moving"]:
            continue
        total_moving += st["dt_moving"]
        total_distance += st["d"]
        factor = _gap_factor(st["grade"])
        gap_time += st["dt_moving"] / factor
        if st["grade"] is not None:
            grade_sum += st["grade"] * st["d"]
            grade_count += st["d"]

    gap_pace = gap_time / (total_distance / 1000.0) if total_distance > 0 else 0.0
    avg_grade = (grade_sum / grade_count * 100.0) if grade_count > 0 else 0.0

    return {
        "gap_pace_s_per_km": round(gap_pace, 1),
        "distance_m": round(total_distance, 1),
        "avg_grade_pct": round(avg_grade, 2),
    }


# ---------------------------------------------------------------------------
# Records / best efforts
# ---------------------------------------------------------------------------
def compute_best_efforts(activity: Activity) -> list[dict]:
    """Best efforts over reference distances, in moving time."""
    valid = [p for p in activity.points if p.lat is not None and p.lon is not None]
    if len(valid) < 2:
        return []

    # Distance and time accumulated over the same "moving" steps to stay
    # consistent (avoids crediting drift distance accumulated during pauses).
    cum_d = [0.0]
    cum_t = [0.0]
    for i in range(1, len(valid)):
        a, b = valid[i - 1], valid[i]
        d = step_distance(a, b)
        dt = (b.time - a.time).total_seconds() if (a.time and b.time) else 0.0
        moving = _is_moving(a, b) and 0 < dt <= MAX_MOVING_GAP
        if moving:
            cum_d.append(cum_d[-1] + d)
            cum_t.append(cum_t[-1] + dt)
        else:
            cum_d.append(cum_d[-1])
            cum_t.append(cum_t[-1])

    total_distance = cum_d[-1]
    efforts = []
    for dist_m, label in BEST_EFFORT_DISTANCES:
        if dist_m > total_distance:
            continue
        best = _best_time(cum_d, cum_t, dist_m)
        if best is None:
            continue
        efforts.append({
            "label": label,
            "distance_m": dist_m,
            "time_s": round(best, 1),
            "pace_s_per_km": round(best / (dist_m / 1000.0), 1),
        })
    return efforts


def _best_time(cum_d: list[float], cum_t: list[float], target: float) -> Optional[float]:
    n = len(cum_d)
    best: Optional[float] = None
    for i in range(n):
        j = bisect_left(cum_d, cum_d[i] + target)
        if j >= n:
            break
        t = cum_t[j] - cum_t[i]
        # Interpolate the last segment to the exact distance
        if j > i:
            excess = cum_d[j] - cum_d[i] - target
            seg_dist = cum_d[j] - cum_d[j - 1]
            seg_time = cum_t[j] - cum_t[j - 1]
            if seg_dist > 0 and excess > 0:
                t -= (excess / seg_dist) * seg_time
        if best is None or t < best:
            best = t
    return best


# ---------------------------------------------------------------------------
# Matched runs (identical routes)
# ---------------------------------------------------------------------------
def _route_signature(points: list[TrackPoint]) -> set[tuple[int, int]]:
    cells: set[tuple[int, int]] = set()
    for p in points:
        if p.lat is None or p.lon is None:
            continue
        cells.add((round(p.lat / MATCH_CELL_DEG), round(p.lon / MATCH_CELL_DEG)))
    return cells


def matched_runs(activities: list[Activity]) -> list[list[Activity]]:
    """Group activities that follow a similar route (heuristic)."""
    if len(activities) < 2:
        return []

    sigs: dict[str, set] = {}
    dists: dict[str, float] = {}
    for a in activities:
        sigs[a.id] = _route_signature(a.points)
        dists[a.id] = compute_stats(a)["distance_m"]

    parent = {a.id: a.id for a in activities}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    n = len(activities)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = activities[i], activities[j]
            da, db = dists[a.id], dists[b.id]
            if da <= 0 or db <= 0:
                continue
            if abs(da - db) / max(da, db) > MATCH_DISTANCE_RATIO:
                continue
            sa, sb = sigs[a.id], sigs[b.id]
            if not sa or not sb:
                continue
            jaccard = len(sa & sb) / len(sa | sb)
            if jaccard >= MATCH_JACCARD_THRESHOLD:
                union(a.id, b.id)

    groups: dict[str, list[Activity]] = {}
    for a in activities:
        groups.setdefault(find(a.id), []).append(a)

    result = []
    for members in groups.values():
        if len(members) >= 2:
            members.sort(key=lambda a: a.start_time or a.name)
            result.append(members)
    result.sort(key=lambda g: g[0].start_time, reverse=True)
    return result


# ---------------------------------------------------------------------------
# Monthly statistics
# ---------------------------------------------------------------------------
def monthly_stats(activities: list[Activity]) -> list[dict]:
    months: dict[str, dict] = {}
    for a in activities:
        if a.start_time is None:
            continue
        key = a.start_time.strftime("%Y-%m")
        m = months.setdefault(key, {
            "month": key,
            "activities": 0,
            "distance_m": 0.0,
            "moving_time_s": 0.0,
            "elevation_gain_m": 0.0,
        })
        st = compute_stats(a)
        m["activities"] += 1
        m["distance_m"] += st["distance_m"]
        m["moving_time_s"] += st["moving_time_s"]
        m["elevation_gain_m"] += st["elevation_gain_m"]

    result = []
    prev: Optional[dict] = None
    for key in sorted(months):
        m = months[key]
        m["distance_m"] = round(m["distance_m"])
        m["moving_time_s"] = round(m["moving_time_s"])
        m["elevation_gain_m"] = round(m["elevation_gain_m"])
        m["avg_pace_s_per_km"] = round(
            m["moving_time_s"] / (m["distance_m"] / 1000.0), 1
        ) if m["distance_m"] > 0 else 0.0
        if prev is not None:
            m["delta_distance_m"] = round(m["distance_m"] - prev["distance_m"])
            m["delta_moving_time_s"] = round(m["moving_time_s"] - prev["moving_time_s"])
            m["delta_activities"] = m["activities"] - prev["activities"]
        result.append(m)
        prev = m
    return result


# ---------------------------------------------------------------------------
# Heatmap
# ---------------------------------------------------------------------------
def heatmap_points(activities: list[Activity], stride: int = 2) -> list[list[float]]:
    pts: list[list[float]] = []
    for a in activities:
        for p in a.points[::stride]:
            if p.lat is not None and p.lon is not None:
                pts.append([p.lat, p.lon])
    return pts
