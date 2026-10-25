"""Advanced activity analysis: splits, laps, pace zones, GAP, records,
matched-route detection, and monthly statistics.
"""

from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, timezone
from typing import Optional

from .activity import compute_stats, is_moving_step, step_distance, step_speed
from .config import (
    BEST_EFFORT_DISTANCES,
    CRITICAL_SPEED_MAX_S,
    CRITICAL_SPEED_MIN_S,
    GAP_FACTOR_MAX,
    GAP_FACTOR_MIN,
    GAP_MAX_ABS_GRADE,
    GAP_WINDOW_M,
    MATCH_CELL_DEG,
    MATCH_DISTANCE_RATIO,
    MATCH_JACCARD_THRESHOLD,
    MAX_MOVING_GAP,
    PACE_ZONES,
)
from .parsers import Activity, TrackPoint


def _is_moving(a: TrackPoint, b: TrackPoint) -> bool:
    return is_moving_step(a, b)


def _smooth_altitudes(
    values: list[Optional[float]], window: int = 5
) -> list[Optional[float]]:
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

    # Cumulative distance, so the gradient can be measured over a real span.
    cumulative = [0.0]
    step_distances = []
    for i in range(1, len(valid)):
        d = step_distance(valid[i - 1], valid[i])
        step_distances.append(d)
        cumulative.append(cumulative[-1] + d)
    grades = _windowed_grades(cumulative, altitudes)

    steps: list[dict] = []
    for i in range(1, len(valid)):
        a, b = valid[i - 1], valid[i]
        d = step_distances[i - 1]
        dt = (b.time - a.time).total_seconds() if (a.time and b.time) else 0.0
        moving = _is_moving(a, b) and 0 < dt <= MAX_MOVING_GAP

        ea, eb = altitudes[i - 1], altitudes[i]
        grade = None
        window_grades = [g for g in (grades[i - 1], grades[i]) if g is not None]
        if window_grades:
            grade = sum(window_grades) / len(window_grades)
        gain = 0.0
        if ea is not None and eb is not None and eb > ea:
            gain = eb - ea

        speed = step_speed(a, b)

        steps.append(
            {
                "d": d,
                "dt": dt,
                "dt_moving": dt if moving else 0.0,
                "grade": grade,
                "speed": speed,
                "gain": gain,
            }
        )
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
        laps.append(
            {
                "index": i + 1,
                "start_time": seg[0].time.isoformat() if seg and seg[0].time else None,
                "distance_m": stats["distance_m"],
                "moving_time_s": stats["moving_time_s"],
                "elapsed_time_s": stats["elapsed_time_s"],
                "pace_s_per_km": stats["avg_pace_s_per_km"],
                "elevation_gain_m": stats["elevation_gain_m"],
                "avg_hr": stats["avg_hr"],
            }
        )
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
def compute_pace_zones(points: list[TrackPoint], use_gap: bool = False) -> dict:
    """Time and distance per pace zone.

    With ``use_gap``, a step is classified on its grade-adjusted pace rather
    than its raw pace, so a climb is not scored as an easy effort just because
    the athlete was moving slowly. Load still uses raw pace: changing that would
    move every historical training-load number.
    """
    steps = _steps(points)
    zones = [
        {
            "name": z["name"],
            "color": z["color"],
            "min": z["min"],
            "max": z["max"],
            "time_s": 0.0,
            "distance_m": 0.0,
        }
        for z in PACE_ZONES
    ]
    total_time = 0.0
    total_distance = 0.0

    for st in steps:
        if not st["dt_moving"] or st["speed"] is None or st["speed"] <= 0:
            continue
        pace = 1000.0 / st["speed"]  # s/km
        if use_gap:
            pace = pace / _gap_factor(st["grade"])
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
        z["percent"] = (
            round(100.0 * z["time_s"] / total_time, 1) if total_time > 0 else 0.0
        )

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
def _minetti_cost(grade: float) -> float:
    """Energy cost of running per metre at a gradient (Minetti et al. 2002).

    J/(kg·m) from ~3.6 on the flat to ~5.97 at +10% and back down through the
    descents. The polynomial is only fitted for -45%..+45%.
    """
    g = max(-GAP_MAX_ABS_GRADE, min(GAP_MAX_ABS_GRADE, grade))
    return 155.4 * g**5 - 30.4 * g**4 - 43.3 * g**3 + 46.3 * g**2 + 19.5 * g + 3.6


def _gap_factor(grade: Optional[float]) -> float:
    """Flat-equivalent speed multiplier for a gradient.

    A factor above 1 means the effort was harder than the speed suggests, so the
    grade-adjusted *pace* is faster than the raw pace (pace / factor).
    """
    if grade is None or grade == 0:
        return 1.0
    flat_cost = _minetti_cost(0.0)
    if flat_cost <= 0:  # pragma: no cover - defensive
        return 1.0
    factor = _minetti_cost(grade) / flat_cost
    return max(GAP_FACTOR_MIN, min(GAP_FACTOR_MAX, factor))


def gap_factor(grade: Optional[float]) -> float:
    """Public alias of the grade correction, for the pacing planner."""
    return _gap_factor(grade)


def _windowed_grades(
    distances: list[float],
    altitudes: list[Optional[float]],
    window: float = GAP_WINDOW_M,
) -> list[Optional[float]]:
    """Gradient at each point, measured over at least ``window`` metres.

    A gradient computed between two 3 m samples is dominated by GPS altitude
    noise. Both pointers advance monotonically, so this stays linear.
    """
    count = len(distances)
    grades: list[Optional[float]] = [None] * count
    if count < 2:
        return grades
    total = distances[-1]
    half = window / 2.0
    lo = hi = 0
    for i in range(count):
        target_lo = max(0.0, distances[i] - half)
        target_hi = min(total, distances[i] + half)
        while lo < count - 1 and distances[lo] < target_lo:
            lo += 1
        while hi < count - 1 and distances[hi] < target_hi:
            hi += 1
        span = distances[hi] - distances[lo]
        if span <= 0 or span < window * 0.5:
            continue
        start, end = altitudes[lo], altitudes[hi]
        if start is None or end is None:
            continue
        grades[i] = (end - start) / span
    return grades


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
        efforts.append(
            {
                "label": label,
                "distance_m": dist_m,
                "time_s": round(best, 1),
                "pace_s_per_km": round(best / (dist_m / 1000.0), 1),
            }
        )
    return efforts


def _best_time(
    cum_d: list[float], cum_t: list[float], target: float
) -> Optional[float]:
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
            members.sort(key=_start_key)
            result.append(members)
    result.sort(key=lambda g: _start_key(g[0]), reverse=True)
    return result


def _start_key(activity: Activity) -> datetime:
    """Sort key that tolerates activities without a start time."""
    start = activity.start_time
    if start is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return start if start.tzinfo else start.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Monthly statistics
# ---------------------------------------------------------------------------
def monthly_stats(activities: list[Activity]) -> list[dict]:
    months: dict[str, dict] = {}
    for a in activities:
        if a.start_time is None:
            continue
        key = a.start_time.astimezone(timezone.utc).strftime("%Y-%m")
        m = months.setdefault(
            key,
            {
                "month": key,
                "activities": 0,
                "distance_m": 0.0,
                "moving_time_s": 0.0,
                "elevation_gain_m": 0.0,
            },
        )
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
        m["avg_pace_s_per_km"] = (
            round(m["moving_time_s"] / (m["distance_m"] / 1000.0), 1)
            if m["distance_m"] > 0
            else 0.0
        )
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


# ---------------------------------------------------------------------------
# Critical speed and durability
# ---------------------------------------------------------------------------
def critical_speed(
    performances: list[dict],
) -> Optional[dict]:
    """Fit the speed-duration model d = CS·t + D' to race performances.

    ``performances`` holds ``{"distance_m", "time_s"}`` entries. A least-squares
    line through distance against time gives the critical speed (the slope, m/s)
    and the finite distance reserve D' (the intercept). Unlike VDOT, which is a
    table built from other athletes, this is fitted to the athlete's own points.

    Returns None when there are fewer than two usable performances or the fit is
    degenerate.
    """
    points = [
        (float(p["time_s"]), float(p["distance_m"]))
        for p in performances
        if p.get("time_s")
        and p.get("distance_m")
        and CRITICAL_SPEED_MIN_S <= p["time_s"] <= CRITICAL_SPEED_MAX_S
    ]
    if len(points) < 2:
        return None

    n = len(points)
    sum_t = sum(t for t, _ in points)
    sum_d = sum(d for _, d in points)
    sum_tt = sum(t * t for t, _ in points)
    sum_td = sum(t * d for t, d in points)
    denominator = n * sum_tt - sum_t**2
    if denominator <= 0:
        return None

    speed = (n * sum_td - sum_t * sum_d) / denominator  # m/s
    reserve = (sum_d - speed * sum_t) / n  # metres
    if speed <= 0:
        return None

    mean_d = sum_d / n
    ss_tot = sum((d - mean_d) ** 2 for _, d in points)
    ss_res = sum((d - (speed * t + reserve)) ** 2 for t, d in points)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else None

    warnings = []
    if len(points) < 3:
        warnings.append("only two efforts: one bad day distorts the fit")
    if r2 is not None and r2 < 0.98:
        warnings.append("the performances are not consistent with one model")

    return {
        "speed_ms": round(speed, 3),
        "pace_s_per_km": round(1000.0 / speed, 1),
        "d_prime_m": round(reserve),
        "r2": round(r2, 4) if r2 is not None else None,
        "points": len(points),
        "warnings": warnings,
    }


def fade_index(points: list[TrackPoint], min_distance_m: float = 0.0) -> Optional[dict]:
    """How much the second half of a run slowed down, in grade-adjusted terms.

    Positive fade means the athlete slowed; negative means a negative split.
    GAP is used so that an uphill second half does not read as fatigue.
    """
    steps = _steps(points)
    total = sum(step["d"] for step in steps if step["dt_moving"])
    if total <= 0 or total < min_distance_m:
        return None

    half = total / 2.0
    cumulative = 0.0
    first_d = first_t = 0.0
    second_d = second_t = 0.0
    for step in steps:
        if not step["dt_moving"]:
            continue
        gap_seconds = step["dt_moving"] / _gap_factor(step["grade"])
        if cumulative + step["d"] <= half:
            first_d += step["d"]
            first_t += gap_seconds
        else:
            second_d += step["d"]
            second_t += gap_seconds
        cumulative += step["d"]

    if first_d <= 0 or second_d <= 0:
        return None
    first_pace = first_t / first_d * 1000.0
    second_pace = second_t / second_d * 1000.0
    if first_pace <= 0:
        return None
    return {
        "distance_m": round(total),
        "first_half_pace_s_per_km": round(first_pace, 1),
        "second_half_pace_s_per_km": round(second_pace, 1),
        "fade_pct": round((second_pace - first_pace) / first_pace * 100.0, 2),
    }
