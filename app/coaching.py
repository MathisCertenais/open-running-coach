"""Coaching analytics: training load, fitness/fatigue/form, injury risk (ACWR),
intensity distribution (80/20), VO2max / race prediction and plan generation.

All models work from pace + duration (+ optional session-RPE), so they remain
valid even though heart-rate data is not available yet. Heart rate can be
plugged in later without reworking the load series.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from math import exp
from typing import Optional

from . import injuries
from .activity import compute_stats
from .analysis import (
    compute_best_efforts,
    compute_pace_zones,
    critical_speed,
    fade_index,
)
from .config import (
    ACWR_ACUTE_DAYS,
    ACWR_BANDS,
    ACWR_CHRONIC_DAYS,
    ACWR_GAP_DAYS,
    ATL_TAU_DAYS,
    CTL_CALIBRATION_DAYS,
    CTL_TAU_DAYS,
    FADE_MIN_DISTANCE_M,
    FADE_TREND_RUNS,
    FORM_NEUTRAL_BAND,
    INTENSITY_GROUPS,
    INTENSITY_ROLLING_DAYS,
    INTENSITY_TARGET,
    INTENSITY_WEEKLY_DAYS,
    LOAD_DIVERGENCE_HIGH,
    LOAD_DIVERGENCE_LOW,
    LOAD_DIVERGENCE_MIN_LOAD,
    PACE_ZONE_WEIGHTS,
    PACE_ZONES,
    PLAN_DEFAULT_SESSIONS,
    PLAN_DEFAULT_WEEKLY_MIN,
    PLAN_DEFAULT_WEEKS,
    PLAN_DELOAD_EVERY,
    PLAN_DELOAD_FACTOR,
    PLAN_EASY_FRACTION,
    PLAN_HARD_FRACTION,
    PLAN_LONG_RUN_FRACTION,
    PLAN_MAX_SESSIONS,
    PLAN_MAX_WEEKS,
    PLAN_MIN_SESSIONS,
    PLAN_PROGRESSION,
    PLAN_RAMP_START,
    PLAN_SUPPORT_DEFAULTS,
    RACE_DISTANCES,
    RACE_WEEKLY_VOLUME_KM,
    RIEGEL_EXPONENT,
    STEPS_SEDENTARY_HIGH,
    STEPS_SEDENTARY_WARN,
    SUPPORT_LOAD_WEIGHTS,
    WEIGHT_LOSS_WARN_PCT_PER_WEEK,
    WORKOUT_LOAD_WEIGHTS,
    WORKOUT_PACES,
    WORKOUT_ZONES,
)
from .parsers import Activity


# ---------------------------------------------------------------------------
# Training load
# ---------------------------------------------------------------------------
def pace_zone_minutes(points: list) -> list[float]:
    """Minutes spent in each pace zone (index-aligned with PACE_ZONES)."""
    zones = compute_pace_zones(points)["zones"]
    return [z["time_s"] / 60.0 for z in zones]


def pace_load(points: list) -> float:
    """Pace-based load: sum over zones of (minutes_in_zone x zone_weight).

    Banister-TRIMP analog on pace: harder (faster) zones count more.
    """
    minutes = pace_zone_minutes(points)
    return sum(minutes[i] * PACE_ZONE_WEIGHTS[i] for i in range(len(minutes)))


def activity_load(activity: Activity, rpe: Optional[int]) -> dict:
    """Training load of one activity.

    Rule: if session-RPE is logged, use RPE x duration (Foster 2001);
    otherwise use the pace-based load. Duration is moving time (minutes).
    """
    stats = compute_stats(activity)
    duration_min = stats["moving_time_s"] / 60.0
    if rpe is not None and duration_min > 0:
        load = rpe * duration_min
        return {
            "source": "rpe",
            "load": round(load, 1),
            "rpe": rpe,
            "duration_min": round(duration_min, 1),
            "pace_load": round(pace_load(activity.points), 1),
        }
    load = pace_load(activity.points)
    return {
        "source": "pace",
        "load": round(load, 1),
        "rpe": None,
        "duration_min": round(duration_min, 1),
        "pace_load": round(load, 1),
    }


def _activity_date(activity: Activity) -> Optional[date]:
    st = activity.start_time
    if st is None:
        return None
    return st.astimezone(timezone.utc).date()


def daily_load_map(
    activities: list[Activity], rpe_map: dict[str, int]
) -> dict[date, dict]:
    """Aggregate activities into a per-day load map (UTC date of start time).

    Each bucket counts how many activities contributed load from RPE versus from
    pace, so the caller can label the day without guessing.
    """
    daily: dict[date, dict] = {}
    for a in activities:
        d = _activity_date(a)
        if d is None:
            continue
        ld = activity_load(a, rpe_map.get(a.id))
        bucket = daily.setdefault(
            d, {"load": 0.0, "activities": 0, "rpe_count": 0, "pace_count": 0}
        )
        bucket["load"] += ld["load"]
        bucket["activities"] += 1
        if ld["source"] == "rpe":
            bucket["rpe_count"] += 1
        else:
            bucket["pace_count"] += 1
    return daily


def _day_source(bucket: dict) -> str:
    """Which load source produced a day's total: ``rpe``, ``pace`` or ``mixed``."""
    has_rpe = bucket["rpe_count"] > 0
    has_pace = bucket["pace_count"] > 0
    if has_rpe and has_pace:
        return "mixed"
    return "rpe" if has_rpe else "pace"


def full_load_series(
    activities: list[Activity],
    rpe_map: dict[str, int],
    today: Optional[date] = None,
) -> list[dict]:
    """Continuous daily training-load series (zero-filled), first activity → today.

    ``today`` defaults to the current UTC date; pass it explicitly in tests so
    the series never depends on the wall clock or on the local time zone.
    """
    daily = daily_load_map(activities, rpe_map)
    if not daily:
        return []
    start = min(daily)
    today = today if today is not None else datetime.now(timezone.utc).date()
    end = max(max(daily), today)

    series: list[dict] = []
    d = start
    while d <= end:
        info = daily.get(d)
        load = info["load"] if info else 0.0
        series.append(
            {
                "date": d.isoformat(),
                "load": round(load, 1),
                "activities": info["activities"] if info else 0,
                "has_rpe": (info["rpe_count"] if info else 0) > 0,
                "source": _day_source(info) if info else None,
            }
        )
        d += timedelta(days=1)
    return series


# ---------------------------------------------------------------------------
# Fitness / fatigue / form (CTL / ATL / TSB)
# ---------------------------------------------------------------------------
def fitness_series(
    activities: list[Activity],
    rpe_map: dict[str, int],
    today: Optional[date] = None,
) -> dict:
    """Coggan Performance Management Chart.

    CTL_today = CTL_yesterday + (TL - CTL_yesterday) / 42
    ATL_today = ATL_yesterday + (TL - ATL_yesterday) / 7
    Form (TSB) = CTL - ATL
    """
    series = full_load_series(activities, rpe_map, today=today)
    if not series:
        return {"days": [], "current": None}

    ctl = atl = 0.0
    days: list[dict] = []
    for index, item in enumerate(series):
        tl = item["load"]
        ctl += (tl - ctl) / CTL_TAU_DAYS
        atl += (tl - atl) / ATL_TAU_DAYS
        tsb = ctl - atl
        # Both averages start at zero, so the first weeks say more about the
        # cold start than about the athlete. Report that instead of a band.
        calibrating = index < CTL_CALIBRATION_DAYS
        days.append(
            {
                "date": item["date"],
                "load": item["load"],
                "ctl": round(ctl, 1),
                "atl": round(atl, 1),
                "tsb": round(tsb, 1),
                "tsb_pct": round(100.0 * tsb / ctl, 1) if ctl > 0 else 0.0,
                "form": "calibrating" if calibrating else _form_band(tsb),
                "calibrating": calibrating,
            }
        )
    return {"days": days, "current": days[-1]}


def _form_band(tsb: float) -> str:
    if tsb > FORM_NEUTRAL_BAND:
        return "fresh"
    if tsb < -FORM_NEUTRAL_BAND:
        return "fatigued"
    return "neutral"


# ---------------------------------------------------------------------------
# Injury risk (ACWR)
# ---------------------------------------------------------------------------
def _rolling_avg(loads: list[float], window: int) -> Optional[float]:
    """Strict windowed average: None until a full window of data is available."""
    if window <= 0 or len(loads) < window:
        return None
    return sum(loads[-window:]) / window


def _acwr_band(acwr: float) -> str:
    for name, lo, hi in ACWR_BANDS:
        if (lo is None or acwr >= lo) and (hi is None or acwr < hi):
            return name
    return "unknown"


def _chronic_average(loads: list[float], index: int) -> Optional[float]:
    """Mean load over days -28..-7, excluding the acute week.

    The chronic window deliberately omits the last seven days: including them
    makes the denominator partly the numerator, which is the mathematical
    coupling criticised by Lolli et al. (2019) and reproduces spurious
    correlations on random data.
    """
    end = index + 1 - ACWR_ACUTE_DAYS
    start = end - ACWR_CHRONIC_DAYS
    if start < 0 or end <= 0:
        return None
    window = loads[start:end]
    if len(window) != ACWR_CHRONIC_DAYS:
        return None
    return sum(window) / ACWR_CHRONIC_DAYS


def acwr_series(
    activities: list[Activity],
    rpe_map: dict[str, int],
    today: Optional[date] = None,
) -> dict:
    """Ratio of recent to longer-term load. Descriptive, not predictive.

    acute   = mean load over the last 7 days
    chronic = mean load over days -28..-7 (the acute week is excluded)
    ratio   = acute / chronic
    """
    series = full_load_series(activities, rpe_map, today=today)
    if not series:
        return {"days": [], "current": None}

    loads = [item["load"] for item in series]
    days: list[dict] = []
    last_active: Optional[int] = None
    for index, item in enumerate(series):
        if item["activities"]:
            last_active = index
        gap_days = None if last_active is None else index - last_active

        acute = _rolling_avg(loads[: index + 1], ACWR_ACUTE_DAYS)
        chronic = _chronic_average(loads, index)

        acwr = None
        band = "no_data"
        if acute is not None and chronic is not None and chronic > 0:
            acwr = acute / chronic
            band = _acwr_band(acwr)
        # A layoff is not "ramping down": after ACWR_GAP_DAYS the number stops
        # being interpretable, so it is withheld rather than shown as low.
        if gap_days is not None and gap_days > ACWR_GAP_DAYS:
            acwr = None
            band = "after_gap"

        days.append(
            {
                "date": item["date"],
                "load": item["load"],
                "acute": round(acute, 1) if acute is not None else None,
                "chronic": round(chronic, 1) if chronic is not None else None,
                "acwr": round(acwr, 2) if acwr is not None else None,
                "band": band,
                "gap_days": gap_days,
            }
        )

    current = next((d for d in reversed(days) if d["acwr"] is not None), None)
    return {"days": days, "current": current}


# ---------------------------------------------------------------------------
# Intensity distribution (80/20)
# ---------------------------------------------------------------------------
def _zone_group_totals(points: list, use_gap: bool = True) -> dict:
    """Group zone time into easy / moderate / hard.

    The distribution is computed on grade-adjusted pace: on a hilly run, raw
    pace puts climbing time in an easier bucket than the effort deserved.
    """
    zones = compute_pace_zones(points, use_gap=use_gap)["zones"]
    groups = {name: {"time_s": 0.0, "distance_m": 0.0} for name in INTENSITY_GROUPS}
    for name, cfg in INTENSITY_GROUPS.items():
        for zi in cfg["zones"]:
            z = zones[zi]
            groups[name]["time_s"] += z["time_s"]
            groups[name]["distance_m"] += z["distance_m"]
    return groups


def load_divergence(
    activities: list[Activity], rpe_map: dict[str, int], limit: int = 5
) -> list[dict]:
    """Runs where the session felt much harder or easier than the pace implies.

    Session-RPE and pace load are different scales, so only large ratios are
    reported: they usually mean heat, fatigue, illness, or a session run at the
    wrong intensity for its purpose.
    """
    flagged = []
    for activity in activities:
        rpe = rpe_map.get(activity.id)
        if rpe is None or activity.start_time is None:
            continue
        payload = activity_load(activity, rpe)
        pace_load = payload["pace_load"]
        if pace_load < LOAD_DIVERGENCE_MIN_LOAD:
            continue
        ratio = payload["load"] / pace_load
        if LOAD_DIVERGENCE_LOW <= ratio <= LOAD_DIVERGENCE_HIGH:
            continue
        flagged.append(
            {
                "activity_id": activity.id,
                "name": activity.name,
                "date": activity.start_time.date().isoformat(),
                "rpe": rpe,
                "rpe_load": payload["load"],
                "pace_load": pace_load,
                "ratio": round(ratio, 2),
                "direction": "harder" if ratio > 1 else "easier",
            }
        )
    flagged.sort(key=lambda item: item["date"], reverse=True)
    return flagged[:limit]


def project_plan(plan: dict, start_ctl: float) -> dict:
    """Project chronic load through a plan, week by week.

    Each session's load is estimated as duration x WORKOUT_LOAD_WEIGHTS[type];
    the weekly total is spread evenly over seven days and pushed through the
    same CTL recursion used by the chart, so the projection is consistent with
    the number the athlete already reads. It is an estimate, not a promise.
    """
    ctl = start_ctl
    weeks = []
    for week in plan.get("weeks_plan", []):
        weekly = sum(
            (session.get("duration_min") or 0)
            * WORKOUT_LOAD_WEIGHTS.get(session.get("type"), 2.0)
            for session in week.get("sessions", [])
        )
        daily = weekly / 7.0
        for _ in range(7):
            ctl += (daily - ctl) / CTL_TAU_DAYS
        weeks.append(
            {
                "week": week.get("week"),
                "type": week.get("type"),
                "weekly_load": round(weekly),
                "projected_ctl": round(ctl, 1),
            }
        )
    peak = max((w["projected_ctl"] for w in weeks), default=round(start_ctl, 1))
    return {
        "start_ctl": round(start_ctl, 1),
        "weeks": weeks,
        "final_ctl": round(ctl, 1),
        "peak_ctl": peak,
        "method": "session minutes x type weight, spread over 7 days, CTL tau 42",
    }


def performance_profile(activities: list[Activity]) -> dict:
    """Critical speed and durability, both derived from what was recorded.

    Critical speed is fitted to the athlete's own best efforts (d = CS·t + D'),
    which needs no heart rate and no reference table. Durability is the fade
    index of runs long enough to say something: how much the second half slowed
    in grade-adjusted terms.
    """
    best: dict[float, dict] = {}
    for activity in activities:
        for effort in compute_best_efforts(activity):
            distance = effort["distance_m"]
            if distance not in best or effort["time_s"] < best[distance]["time_s"]:
                best[distance] = {
                    "distance_m": distance,
                    "time_s": effort["time_s"],
                    "label": effort["label"],
                }

    fit = critical_speed(list(best.values()))

    runs = []
    for activity in activities:
        if activity.start_time is None:
            continue
        fade = fade_index(activity.points, FADE_MIN_DISTANCE_M)
        if not fade:
            continue
        runs.append(
            {
                **fade,
                "date": activity.start_time.date().isoformat(),
                "name": activity.name,
                "activity_id": activity.id,
            }
        )
    runs.sort(key=lambda run: run["date"], reverse=True)

    def _mean_fade(items):
        values = [r["fade_pct"] for r in items]
        return round(sum(values) / len(values), 2) if values else None

    recent = runs[:FADE_TREND_RUNS]
    previous = runs[FADE_TREND_RUNS : FADE_TREND_RUNS * 2]
    recent_avg = _mean_fade(recent)
    previous_avg = _mean_fade(previous)
    trend = (
        round(recent_avg - previous_avg, 2)
        if recent_avg is not None and previous_avg is not None
        else None
    )

    return {
        "critical_speed": fit,
        "durability": {
            "runs": runs[:10],
            "min_distance_m": FADE_MIN_DISTANCE_M,
            "recent_avg_fade_pct": recent_avg,
            "previous_avg_fade_pct": previous_avg,
            "trend_pct": trend,
            "runs_compared": [len(recent), len(previous)],
        },
    }


def intensity_distribution(activities: list[Activity]) -> dict:
    """Time split across easy / moderate / hard (by grade-adjusted pace)."""

    def _window(days: int) -> dict:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)
        groups = {name: {"time_s": 0.0, "distance_m": 0.0} for name in INTENSITY_GROUPS}
        for a in activities:
            st = a.start_time
            if st is None or st.astimezone(timezone.utc) < cutoff:
                continue
            g = _zone_group_totals(a.points)
            for name in groups:
                groups[name]["time_s"] += g[name]["time_s"]
                groups[name]["distance_m"] += g[name]["distance_m"]
        return _finalize_groups(groups, days)

    return {
        "weekly": _window(INTENSITY_WEEKLY_DAYS),
        "rolling": _window(INTENSITY_ROLLING_DAYS),
        "target": INTENSITY_TARGET,
    }


def _finalize_groups(groups: dict, days: int) -> dict:
    total_time = sum(g["time_s"] for g in groups.values())
    total_dist = sum(g["distance_m"] for g in groups.values())
    out = {}
    for name, g in groups.items():
        out[name] = {
            "time_s": round(g["time_s"], 1),
            "distance_m": round(g["distance_m"], 1),
            "time_pct": round(100.0 * g["time_s"] / total_time, 1)
            if total_time > 0
            else 0.0,
            "distance_pct": round(100.0 * g["distance_m"] / total_dist, 1)
            if total_dist > 0
            else 0.0,
            "color": INTENSITY_GROUPS[name]["color"],
        }
    return {
        "window_days": days,
        "groups": out,
        "total_time_s": round(total_time, 1),
        "total_distance_m": round(total_dist, 1),
    }


# ---------------------------------------------------------------------------
# VO2max & race prediction
# ---------------------------------------------------------------------------
def _vdot(distance_m: float, time_s: float) -> Optional[float]:
    """Daniels' VDOT from a race performance (distance, moving time).

    VO2max estimate using the published VDOT formula (Daniels' Running Formula):
      %VO2max = 0.8 + 0.1894393*e^(-0.012778*t) + 0.2989558*e^(-0.1932605*t)
      VO2     = -4.60 + 0.182258*v + 0.000104*v^2   (v in m/min)
      VDOT    = VO2 / %VO2max
    """
    t_min = time_s / 60.0
    if t_min <= 0 or distance_m <= 0:
        return None
    v = distance_m / t_min  # m/min
    pct = 0.8 + 0.1894393 * exp(-0.012778 * t_min) + 0.2989558 * exp(-0.1932605 * t_min)
    vo2 = -4.60 + 0.182258 * v + 0.000104 * v * v
    if pct <= 0:
        return None
    return vo2 / pct


def _riegel(
    seed_distance_m: float, seed_time_s: float, target_distance_m: float
) -> float:
    """Riegel prediction: T2 = T1 * (D2 / D1)^exponent."""
    return seed_time_s * (target_distance_m / seed_distance_m) ** RIEGEL_EXPONENT


def vo2max_and_predictions(activities: list[Activity]) -> dict:
    """Effective VO2max from recent best efforts + race-time predictions."""
    # All-time best time per reference distance (from per-activity best efforts).
    best: dict[float, dict] = {}
    for a in activities:
        for eff in compute_best_efforts(a):
            d = eff["distance_m"]
            if d not in best or eff["time_s"] < best[d]["time_s"]:
                best[d] = {
                    "distance_m": d,
                    "label": eff["label"],
                    "time_s": eff["time_s"],
                    "pace_s_per_km": eff["pace_s_per_km"],
                    "date": a.start_time.isoformat() if a.start_time else None,
                    "activity_id": a.id,
                }

    if not best:
        return {"effective_vo2max": None, "seed": None, "predictions": []}

    # Effective VO2max = highest VDOT across all reference performances.
    perfs = []
    for info in best.values():
        vd = _vdot(info["distance_m"], info["time_s"])
        perfs.append({**info, "vdot": round(vd, 1) if vd is not None else None})

    seed = max(
        (p for p in perfs if p["vdot"] is not None),
        key=lambda p: p["vdot"],
        default=None,
    )
    effective = seed["vdot"] if seed else None

    predictions = []
    if seed is not None:
        for dist_m, label in RACE_DISTANCES:
            pred = _riegel(seed["distance_m"], seed["time_s"], dist_m)
            actual = best.get(dist_m)
            predictions.append(
                {
                    "label": label,
                    "distance_m": dist_m,
                    "predicted_time_s": round(pred, 1),
                    "predicted_pace_s_per_km": round(pred / (dist_m / 1000.0), 1),
                    "actual_time_s": round(actual["time_s"], 1) if actual else None,
                    "actual_pace_s_per_km": actual["pace_s_per_km"] if actual else None,
                    "actual_date": actual["date"] if actual else None,
                }
            )

    return {
        "effective_vo2max": effective,
        "seed": seed,
        "performances": perfs,
        "predictions": predictions,
    }


# ---------------------------------------------------------------------------
# Plan generation (periodization)
# ---------------------------------------------------------------------------
def _estimate_recent_weekly_min(activities: list[Activity]) -> Optional[float]:
    """Average weekly moving time (minutes) over the last 28 days."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=28)
    total_s = 0.0
    for a in activities:
        st = a.start_time
        if st is None or st.astimezone(timezone.utc) < cutoff:
            continue
        total_s += compute_stats(a)["moving_time_s"]
    weeks = 4.0
    return total_s / 60.0 / weeks if total_s > 0 else None


def _race_weekly_min(goal_distance_m: float) -> float:
    """Suggested peak weekly volume (minutes) for a race distance.

    Used as a floor so a race plan stays sensible even when the athlete has
    little recent data to infer volume from history.
    """
    closest = min(RACE_WEEKLY_VOLUME_KM, key=lambda d: abs(d - goal_distance_m))
    weekly_km = RACE_WEEKLY_VOLUME_KM[closest]
    return weekly_km * (WORKOUT_PACES["easy"] / 60.0)


def _build_week(week_index: int, volume_min: float, sessions_per_week: int) -> dict:
    """Split a week's volume (minutes) into sessions following the 80/20 rule."""
    easy_min = volume_min * PLAN_EASY_FRACTION
    hard_min = volume_min * PLAN_HARD_FRACTION
    long_min = round(volume_min * PLAN_LONG_RUN_FRACTION)

    hard_count = 1 if sessions_per_week <= 4 else 2
    has_recovery = sessions_per_week >= 4
    recovery_min = round(volume_min * 0.15) if has_recovery else 0

    easy_remaining = easy_min - long_min - recovery_min
    easy_count = max(0, sessions_per_week - 1 - (1 if has_recovery else 0) - hard_count)
    if easy_count <= 0:
        easy_remaining = max(0.0, easy_remaining)
        easy_count = 1

    tempo_min = hard_min * (0.5 if hard_count == 2 else 1.0)
    interval_min = hard_min - tempo_min

    sessions: list[dict] = []

    def _add(workout_type: str, minutes: float) -> None:
        minutes = max(15, round(minutes))
        sessions.append(
            {
                "type": workout_type,
                "duration_min": minutes,
                "distance_km": round(minutes * 60.0 / WORKOUT_PACES[workout_type], 1),
                "zones": WORKOUT_ZONES[workout_type],
                "description": _workout_description(workout_type),
            }
        )

    # Easy sessions first (base), then hard, recovery, long run last.
    for _ in range(easy_count):
        _add("easy", easy_remaining / easy_count)
    if hard_count >= 1:
        _add("tempo", tempo_min)
    if hard_count >= 2:
        _add("intervals", interval_min)
    if has_recovery:
        _add("recovery", recovery_min)
    _add("long_run", long_min)

    for i, s in enumerate(sessions):
        s["day_offset"] = i

    week_type = "deload" if (week_index + 1) % PLAN_DELOAD_EVERY == 0 else "build"
    return {
        "week": week_index + 1,
        "type": week_type,
        "volume_min": round(volume_min),
        "sessions": sessions,
    }


def _workout_description(workout_type: str) -> str:
    return {
        "recovery": "Recovery run (Z1) — very easy, conversational. Flush out fatigue.",
        "easy": "Easy run (Z2) — aerobic base, conversational pace.",
        "long_run": "Long run (Z2) — build endurance, steady effort.",
        "tempo": "Tempo run (Z3–Z4) — comfortably hard, threshold effort.",
        "intervals": "Intervals (Z4–Z5) — repeat efforts at VO2max pace with recovery.",
    }[workout_type]


def generate_plan(
    activities: list[Activity],
    name: str = "",
    goal_distance_m: Optional[float] = None,
    goal_date: Optional[str] = None,
    weekly_target_m: Optional[float] = None,
    weekly_target_s: Optional[float] = None,
    sessions_per_week: int = PLAN_DEFAULT_SESSIONS,
    start_date: Optional[str] = None,
) -> dict:
    """Generate a periodized plan (weeks -> sessions).

    - Race goal (distance + date) or weekly volume target (distance or time).
    - 80/20 distribution, ~+10% weekly progression, deload every 4th week.
    - Support sessions (strength, mobility, rest) are scheduled as planned
      sessions, reduced during the taper week.
    """
    sessions_per_week = max(
        PLAN_MIN_SESSIONS, min(PLAN_MAX_SESSIONS, int(sessions_per_week))
    )
    base_date = date.today()
    if start_date:
        try:
            base_date = datetime.strptime(start_date, "%Y-%m-%d").date()
        except ValueError:
            pass

    # 1. Determine peak weekly volume (minutes).
    if weekly_target_s is not None and weekly_target_s > 0:
        peak_weekly_min = weekly_target_s / 60.0
    elif weekly_target_m is not None and weekly_target_m > 0:
        peak_weekly_min = (weekly_target_m / 1000.0) * (WORKOUT_PACES["easy"] / 60.0)
    else:
        recent = _estimate_recent_weekly_min(activities)
        peak_weekly_min = (recent * 1.15) if recent else PLAN_DEFAULT_WEEKLY_MIN
        if goal_distance_m:
            peak_weekly_min = max(peak_weekly_min, _race_weekly_min(goal_distance_m))

    # 2. Determine number of weeks.
    weeks = PLAN_DEFAULT_WEEKS
    goal_desc = "Weekly volume target"
    if goal_date:
        try:
            target = datetime.strptime(goal_date, "%Y-%m-%d").date()
            diff = (target - base_date).days
            if diff > 0:
                weeks = max(1, min(PLAN_MAX_WEEKS, int(round(diff / 7.0))))
        except ValueError:
            pass
    if goal_distance_m:
        label = next(
            (lbl for d, lbl in RACE_DISTANCES if abs(d - goal_distance_m) < 1), None
        )
        if goal_date:
            goal_desc = f"Race: {label or (round(goal_distance_m / 1000, 1)) + ' km'} on {goal_date}"
        else:
            goal_desc = f"Race: {label or (round(goal_distance_m / 1000, 1)) + ' km'}"

    # 3. Weekly volume ramp: +10% per week from a 60% start, capped at peak,
    #    with every 4th week stepped back to PLAN_DELOAD_FACTOR of the previous
    #    build week (a deload is a reduction, not a slower increase).
    plan_weeks = []
    current = peak_weekly_min * PLAN_RAMP_START
    for i in range(weeks):
        is_deload = (i + 1) % PLAN_DELOAD_EVERY == 0
        if not is_deload and i:
            current = min(peak_weekly_min, current * PLAN_PROGRESSION)
        volume = current * PLAN_DELOAD_FACTOR if is_deload else current
        plan_weeks.append(_build_week(i, volume, sessions_per_week))

    # Support sessions with absolute dates. Strength is dropped in the taper
    # (last) week; mobility and rest stay.
    support_sessions: list[dict] = []
    for i in range(weeks):
        is_taper = weeks > 1 and i == weeks - 1
        for default in PLAN_SUPPORT_DEFAULTS:
            if is_taper and default["kind"] == "strength":
                continue
            session_date = base_date + timedelta(days=7 * i + default["day_offset"])
            support_sessions.append(
                {
                    "date": session_date.isoformat(),
                    "time": "",
                    "kind": default["kind"],
                    "title": default["title"],
                    "duration_min": default["duration_min"],
                    "rpe": default["rpe"],
                    "focus": list(default["focus"]),
                    "status": "planned",
                    "week": i + 1,
                    "source": "plan",
                }
            )

    return {
        "name": name.strip() or "Training plan",
        "goal_description": goal_desc,
        "weeks": weeks,
        "sessions_per_week": sessions_per_week,
        "peak_weekly_min": round(peak_weekly_min),
        "start_date": base_date.isoformat(),
        "weeks_plan": plan_weeks,
        "support_sessions": support_sessions,
    }


# ---------------------------------------------------------------------------
# Public helpers for the API
# ---------------------------------------------------------------------------
def zone_definitions() -> list[dict]:
    """Human-readable pace-zone table (for UI explanations)."""
    return [
        {
            "index": i,
            "name": z["name"],
            "weight": PACE_ZONE_WEIGHTS[i],
            "color": z["color"],
            "min": z["min"],
            "max": z["max"],
        }
        for i, z in enumerate(PACE_ZONES)
    ]


# ---------------------------------------------------------------------------
# Coach context (compact, privacy-conscious snapshot for the LLM)
# ---------------------------------------------------------------------------
def _to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _age_from_birth(birth_date: Optional[str]) -> Optional[int]:
    if not birth_date:
        return None
    try:
        b = datetime.strptime(str(birth_date)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    today = date.today()
    age = today.year - b.year - ((today.month, today.day) < (b.month, b.day))
    return age if 0 <= age < 130 else None


def _utc_sort_key(activity: Activity):
    return activity.start_time or datetime.min.replace(tzinfo=timezone.utc)


def build_snapshot(
    activities: list[Activity],
    rpe_map: dict[str, int],
    profile: dict,
    weights: list[dict],
    shoes: list[dict],
    goals: list[dict],
    notes: dict[str, str],
    recent_n: int = 10,
    feedback_map: Optional[dict] = None,
    sessions: Optional[list] = None,
    nutrition: Optional[list] = None,
    supplements: Optional[list] = None,
) -> dict:
    """Assemble a compact athlete snapshot for the LLM coach.

    Only derived metrics are sent — never raw GPS coordinates — so the
    athlete's routes and home location are not exposed.
    """
    profile = profile or {}
    notes = notes or {}
    weights = weights or []
    feedback_map = feedback_map or {}
    sessions = sessions or []
    nutrition = nutrition or []
    supplements = supplements or []

    # Athlete.
    height = _to_float(profile.get("height_cm"))
    latest_weight = weights[0]["weight_kg"] if weights else None
    bmi = (
        (latest_weight / (height / 100.0) ** 2) if (latest_weight and height) else None
    )
    athlete = {
        "name": profile.get("name") or None,
        "age": _age_from_birth(profile.get("birth_date")),
        "height_cm": height,
        "weight_kg": latest_weight,
        "bmi": round(bmi, 1) if bmi else None,
    }

    # Load series and rolling sums.
    series = full_load_series(activities, rpe_map)
    loads = [d["load"] for d in series]
    last_7d = round(sum(loads[-7:]), 1) if loads else 0.0
    prev_7d = round(sum(loads[-14:-7]), 1) if len(loads) > 7 else 0.0
    last_28d = round(sum(loads[-28:]), 1) if loads else 0.0

    dated = [a.start_time for a in activities if a.start_time]
    last_date = max(dated).date() if dated else None
    days_since = (date.today() - last_date).days if last_date else None

    fit = fitness_series(activities, rpe_map)
    cur_fit = fit.get("current") or {}
    acwr = acwr_series(activities, rpe_map).get("current") or {}
    inten = intensity_distribution(activities)["rolling"]
    vo2 = vo2max_and_predictions(activities)

    # All-time best efforts (compact).
    best: dict[float, dict] = {}
    for a in activities:
        for eff in compute_best_efforts(a):
            d = eff["distance_m"]
            if d not in best or eff["time_s"] < best[d]["time_s"]:
                best[d] = {
                    "label": eff["label"],
                    "distance_m": d,
                    "time_s": eff["time_s"],
                    "pace_s_per_km": eff["pace_s_per_km"],
                }
    best_list = sorted(best.values(), key=lambda x: x["distance_m"])

    # Recent activities, most recent first (with post-run feedback).
    recent = []
    for a in sorted(activities, key=_utc_sort_key, reverse=True)[:recent_n]:
        st = compute_stats(a)
        note = notes.get(a.id) or (a.description or "")
        fb = feedback_map.get(a.id) or {}
        recent.append(
            {
                "date": a.start_time.date().isoformat() if a.start_time else None,
                "type": a.activity_type,
                "distance_km": round(st["distance_m"] / 1000.0, 2),
                "moving_min": round(st["moving_time_s"] / 60.0, 1),
                "pace_s_per_km": st["avg_pace_s_per_km"],
                "rpe": rpe_map.get(a.id),
                "note": note[:200] if note else "",
                "session_type": fb.get("session_type") or None,
                "surface": fb.get("surface") or None,
                "completed": fb.get("completed") or None,
                "readiness": fb.get("readiness"),
                "sleep_quality": fb.get("sleep_quality"),
                "stress": fb.get("stress"),
                "legs": fb.get("legs"),
                "pain": bool(fb.get("pain")),
                "pain_location": fb.get("pain_location") or None,
                "pain_side": fb.get("pain_side") or None,
                "pain_severity": fb.get("pain_severity"),
                "pain_timing": fb.get("pain_timing") or None,
                "pain_trend": fb.get("pain_trend") or None,
                "is_race": bool(fb.get("is_race")),
            }
        )

    def _avg(field):
        vals = [r[field] for r in recent if isinstance(r.get(field), (int, float))]
        return round(sum(vals) / len(vals), 1) if vals else None

    pain_runs = [r for r in recent if r.get("pain")]
    wellness = {
        "readiness_avg_10": _avg("readiness"),
        "sleep_avg_10": _avg("sleep_quality"),
        "stress_avg_10": _avg("stress"),
        "legs_avg_10": _avg("legs"),
        "pain_runs_10": len(pain_runs),
        "pain_locations_10": sorted(
            {r.get("pain_location") for r in pain_runs if r.get("pain_location")}
        ),
        "pain_worsening_10": sum(
            1 for r in pain_runs if r.get("pain_trend") == "worse"
        ),
    }

    # Support sessions (strength/mobility/cross/rest), rolling windows.
    today = date.today()

    def _within(session, days):
        try:
            sd = date.fromisoformat(session.get("date", ""))
        except (ValueError, TypeError):
            return False
        return 0 <= (today - sd).days < days

    def _support_load(items):
        total = 0.0
        for s in items:
            weight = SUPPORT_LOAD_WEIGHTS.get(s.get("kind", "other"), 0.2)
            total += (s.get("rpe") or 0) * (s.get("duration_min") or 0) * weight
        return round(total, 1)

    support_7 = [s for s in sessions if _within(s, 7) and s.get("status") != "skipped"]
    support_28 = [
        s for s in sessions if _within(s, 28) and s.get("status") != "skipped"
    ]
    support = {
        "sessions_7d": len(support_7),
        "sessions_28d": len(support_28),
        "strength_7d": sum(1 for s in support_7 if s.get("kind") == "strength"),
        "mobility_7d": sum(1 for s in support_7 if s.get("kind") == "mobility"),
        "completed_7d": sum(1 for s in support_7 if s.get("status") == "completed"),
        "planned_7d": sum(1 for s in support_7 if s.get("status") == "planned"),
        "support_load_7d": _support_load(support_7),
        "support_load_28d": _support_load(support_28),
    }

    # Fuel & recovery (optional) and weight trend.
    def _safe_date(value):
        try:
            return date.fromisoformat(str(value)[:10])
        except (ValueError, TypeError):
            return None

    def _weight_trend(items):
        if not items:
            return None
        ordered = sorted(items, key=lambda w: w.get("date", ""))
        latest = ordered[-1]
        latest_date = _safe_date(latest.get("date"))
        if latest_date is None:
            return {"latest_kg": latest.get("weight_kg"), "pct_per_week": None}
        window = [
            w
            for w in ordered
            if _safe_date(w.get("date"))
            and 0 <= (latest_date - _safe_date(w.get("date"))).days <= 28
        ]
        if len(window) < 2:
            return {"latest_kg": latest.get("weight_kg"), "pct_per_week": None}
        first = window[0]
        days = (latest_date - _safe_date(first.get("date"))).days
        if days <= 0 or not first.get("weight_kg"):
            return {"latest_kg": latest.get("weight_kg"), "pct_per_week": None}
        pct = (latest["weight_kg"] - first["weight_kg"]) / first["weight_kg"] * 100
        return {
            "latest_kg": latest.get("weight_kg"),
            "pct_per_week": round(pct * 7 / days, 2),
            "window_days": days,
        }

    nutrition_7 = [
        n
        for n in nutrition
        if _safe_date(n.get("date"))
        and 0 <= (date.today() - _safe_date(n.get("date"))).days < 7
    ]

    def _avg_nut(field):
        vals = [n[field] for n in nutrition_7 if isinstance(n.get(field), (int, float))]
        return round(sum(vals) / len(vals), 1) if vals else None

    def _avg_macro(key):
        vals = [
            (n.get("macros") or {}).get(key)
            for n in nutrition_7
            if isinstance((n.get("macros") or {}).get(key), (int, float))
        ]
        return round(sum(vals) / len(vals)) if vals else None

    supplement_summary = []
    for s in supplements:
        if not s.get("active", True):
            continue
        taken = sum(
            1 for n in nutrition_7 if s.get("id") in (n.get("supplements_taken") or [])
        )
        supplement_summary.append({"name": s.get("name"), "taken_days_7d": taken})

    nutrition_summary = {
        "logs_7d": len(nutrition_7),
        "hydration_avg_l": _avg_nut("hydration_l"),
        "energy_avg": _avg_nut("energy"),
        "appetite_avg": _avg_nut("appetite"),
        "steps_avg_7d": _avg_nut("steps"),
        "calories_avg_7d": _avg_macro("calories"),
        "protein_avg_7d": _avg_macro("protein_g"),
        "carbs_avg_7d": _avg_macro("carbs_g"),
        "fat_avg_7d": _avg_macro("fat_g"),
        "fueling_days_7d": sum(
            1
            for n in nutrition_7
            if n.get("fueling_before")
            or n.get("fueling_during")
            or n.get("fueling_after")
        ),
        "supplements": supplement_summary,
        "weight": _weight_trend(weights),
    }

    shoe_list = []
    for s in shoes:
        shoe_list.append(
            {
                "name": s.get("name"),
                "km": round((s.get("distance_m") or 0) / 1000.0, 1),
                "threshold_km": s.get("threshold_km"),
                "retired": bool(s.get("retired")),
            }
        )

    goal_list = []
    for g in goals:
        p = g.get("progress") or {}
        goal_list.append(
            {
                "period": g.get("period"),
                "metric": g.get("metric"),
                "target": g.get("target"),
                "current": p.get("current"),
                "percent": p.get("percent"),
            }
        )

    # --- new analyses: injury links, divergence, conditions -----------------
    checked_at = date.today()
    activity_dates = {
        a.id: a.start_time.astimezone(timezone.utc).date().isoformat()
        for a in activities
        if a.start_time
    }
    episode_list = injuries.build_episodes(
        feedback_map, activity_dates, today=checked_at
    )
    linked = injuries.link_sessions_to_episodes(
        episode_list, sessions, today=checked_at
    )
    injury_summary = {
        "episodes": [
            {
                "location": e["location"],
                "side": e["side"],
                "first_date": e["first_date"],
                "last_date": e["last_date"],
                "reports": e["reports"],
                "max_severity": e["max_severity"],
                "active": e["active"],
                "verdict": e.get("verdict"),
            }
            for e in episode_list
        ],
        "links": [
            {
                "location": link["location"],
                "pain_first_date": link["pain_first_date"],
                "session_date": link["session_date"],
                "session_title": link["session_title"],
                "session_rpe": link["session_rpe"],
                "hours_before": link["hours_before"],
                "explanation": link["explanation"],
            }
            for link in linked["links"]
        ],
        "observed_rate": linked["summary"].get("observed_rate"),
        "base_rate": linked["summary"].get("base_rate"),
        "reading": linked["summary"].get("reading"),
    }

    conditions: dict[str, int] = {}
    for fb in feedback_map.values():
        label = fb.get("conditions")
        if label:
            conditions[label] = conditions.get(label, 0) + 1

    sessions_detail = [
        {
            "date": s.get("date"),
            "kind": s.get("kind"),
            "title": s.get("title"),
            "rpe": s.get("rpe"),
            "exercises": [e.get("name") for e in s.get("exercises") or []],
        }
        for s in sorted(sessions, key=lambda x: x.get("date") or "", reverse=True)[:5]
    ]

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "athlete": athlete,
        "goals": goal_list,
        "fitness": {
            "date": cur_fit.get("date"),
            "ctl": cur_fit.get("ctl"),
            "atl": cur_fit.get("atl"),
            "tsb": cur_fit.get("tsb"),
            "form": cur_fit.get("form"),
            "form_pct_of_ctl": cur_fit.get("tsb_pct"),
            "calibrating": cur_fit.get("calibrating"),
        },
        "calibration": {
            "days_required": CTL_CALIBRATION_DAYS,
            "in_calibration": cur_fit.get("calibrating"),
            "meaning": "both averages start at zero; no form band is meaningful yet",
        },
        "load_change": {
            "ratio": acwr.get("acwr"),
            "band": acwr.get("band"),
            "gap_days": acwr.get("gap_days"),
            "meaning": "describes how fast load is changing; it is not a risk score",
        },
        "load": {
            "last_7d": last_7d,
            "prev_7d": prev_7d,
            "last_28d": last_28d,
            "days_since_last_run": days_since,
            "last_activity_date": last_date.isoformat() if last_date else None,
        },
        "acwr": {
            "ratio": acwr.get("acwr"),
            "band": acwr.get("band"),
            "acute_load_7d": acwr.get("acute"),
            "chronic_load_28d": acwr.get("chronic"),
        },
        "intensity_28d": {
            "easy_pct": inten["groups"]["easy"]["time_pct"],
            "moderate_pct": inten["groups"]["moderate"]["time_pct"],
            "hard_pct": inten["groups"]["hard"]["time_pct"],
            "target_pct": {"easy": 80, "moderate": 10, "hard": 10},
            "basis": "grade-adjusted pace",
        },
        "divergence": load_divergence(activities, rpe_map, limit=3),
        "injuries": injury_summary,
        "conditions": conditions,
        "sessions_detail": sessions_detail,
        "wellness": wellness,
        "support": support,
        "nutrition": nutrition_summary,
        "vo2max": {
            "effective": vo2.get("effective_vo2max"),
            "seed_label": (vo2.get("seed") or {}).get("label"),
            "predictions": [
                {
                    "label": p["label"],
                    "predicted_time_s": p["predicted_time_s"],
                    "actual_time_s": p["actual_time_s"],
                }
                for p in vo2.get("predictions", [])
            ],
        },
        "best_efforts": best_list,
        "recent_activities": recent,
        "shoes": shoe_list,
    }
    snapshot["key_facts"] = _key_facts(snapshot)
    snapshot["red_flags"] = [
        {"level": item["level"], "title": item["title"]}
        for item in rule_based_insights(snapshot)
    ]
    return snapshot


def _key_facts(snapshot: dict) -> list[str]:
    """Unambiguous, pre-formatted facts to reduce LLM misreadings."""
    facts: list[str] = []

    load_change = snapshot.get("load_change") or {}
    if load_change.get("gap_days") is not None and load_change["gap_days"] > 7:
        facts.append(
            f"Load-change ratio is withheld: no activity for "
            f"{load_change['gap_days']} days, so the comparison is meaningless."
        )
    if snapshot.get("calibration", {}).get("in_calibration"):
        facts.append(
            "CTL/ATL are still calibrating (fewer than "
            f"{snapshot['calibration']['days_required']} days of history): do not "
            "describe form as fresh or fatigued."
        )

    injury = snapshot.get("injuries") or {}
    if injury.get("episodes"):
        active = [e for e in injury["episodes"] if e.get("active")]
        facts.append(
            f"{len(injury['episodes'])} pain episode(s), {len(active)} active; "
            f"{len(injury.get('links') or [])} link(s) to a hard session."
        )
        if injury.get("base_rate") is not None:
            facts.append(
                f"Injury links: observed in {injury.get('observed_rate')} of lower-limb "
                f"episodes vs a base rate of {injury['base_rate']} of all days "
                f"({injury.get('reading')}). This is a correlation, not a cause."
            )

    for item in snapshot.get("divergence") or []:
        facts.append(
            f"{item['date']} felt {item['direction']} than the pace suggests: "
            f"RPE {item['rpe']} is {item['ratio']}x the pace-based load."
        )

    if snapshot.get("conditions"):
        summary = ", ".join(f"{k} x{v}" for k, v in snapshot["conditions"].items())
        facts.append(f"Recorded conditions: {summary}.")

    acwr = snapshot.get("acwr") or {}
    if acwr.get("ratio") is not None:
        facts.append(
            f"Load change {acwr['ratio']} ({acwr.get('band')}); "
            f"7-day load {acwr.get('acute_load_7d')}, "
            f"chronic 28-day load {acwr.get('chronic_load_28d')}"
        )

    fit = snapshot.get("fitness") or {}
    if fit.get("tsb") is not None:
        facts.append(
            f"Fitness CTL {fit.get('ctl')}, fatigue ATL {fit.get('atl')}, "
            f"form TSB {fit.get('tsb'):+} ({fit.get('form')})"
        )

    inten = snapshot.get("intensity_28d") or {}
    if inten.get("easy_pct") is not None:
        facts.append(
            f"Intensity last 28 days: {inten['easy_pct']}% easy / "
            f"{inten['moderate_pct']}% moderate / {inten['hard_pct']}% hard "
            "(target 80/10/10)"
        )

    load = snapshot.get("load") or {}
    if load.get("last_7d") is not None:
        facts.append(
            f"Load this week {load['last_7d']} vs previous week {load['prev_7d']}"
        )
        prev = load.get("prev_7d")
        if prev:
            pct = round((load["last_7d"] / prev - 1) * 100)
            facts.append(f"Week-on-week load change: {pct:+d}%")

    vo2 = snapshot.get("vo2max") or {}
    if vo2.get("effective"):
        facts.append(f"Effective VO2max {vo2['effective']} ml/kg/min")

    if load.get("last_activity_date"):
        facts.append(
            f"Last run {load['last_activity_date']} "
            f"({load.get('days_since_last_run')} days ago)"
        )

    nutrition = snapshot.get("nutrition") or {}
    steps = nutrition.get("steps_avg_7d")
    if steps is not None:
        facts.append(f"Daily steps (7-day average): {round(steps)}")

    return facts


def rule_based_insights(snapshot: dict) -> list[dict]:
    """Deterministic coaching observations derived from the snapshot.

    These work offline and double as the red flags handed to the LLM, so the
    model never has to discover them itself.
    """
    insights: list[dict] = []

    load_change = snapshot.get("load_change") or {}
    val, band = load_change.get("ratio"), load_change.get("band")
    if val is not None:
        if band == "sharp_increase":
            insights.append(
                {
                    "level": "warn",
                    "title": "Load rose sharply",
                    "text": f"Your 7-day load is {val:.2f}x the previous 28 days. That is a "
                    "steep change; holding this week steady is usually more productive than "
                    "adding more. This describes the change, not an injury risk.",
                }
            )
        elif band == "ramping_up":
            insights.append(
                {
                    "level": "info",
                    "title": "Load ramping up",
                    "text": f"Your 7-day load is {val:.2f}x the previous 28 days. Reasonable "
                    "during a build — keep increases under ~10% per week.",
                }
            )
        elif band == "ramping_down":
            insights.append(
                {
                    "level": "info",
                    "title": "Load ramping down",
                    "text": f"Your 7-day load is {val:.2f}x the previous 28 days. Fine after a "
                    "race or a deload; rebuild gradually rather than in one big week.",
                }
            )
        elif band == "steady":
            insights.append(
                {
                    "level": "good",
                    "title": "Load steady",
                    "text": f"Your 7-day load is {val:.2f}x the previous 28 days — a stable "
                    "progression.",
                }
            )
    if band == "after_gap":
        insights.append(
            {
                "level": "info",
                "title": "Back after a break",
                "text": "More than a week without training, so the load ratio is withheld. "
                "Restart with easy volume before resuming quality work.",
            }
        )

    fit = snapshot.get("fitness") or {}
    tsb = fit.get("tsb")
    if tsb is not None:
        if tsb < -20:
            insights.append(
                {
                    "level": "warn",
                    "title": "High accumulated fatigue",
                    "text": f"Your form (TSB) is {tsb:+.0f}. Consider an easier day or a recovery "
                    "week before the next hard session.",
                }
            )
        elif tsb > 15:
            insights.append(
                {
                    "level": "good",
                    "title": "Fresh legs",
                    "text": f"Your form (TSB) is {tsb:+.0f} — a good window for a key workout or a race.",
                }
            )

    inten = snapshot.get("intensity_28d") or {}
    easy, mod, hard = (
        inten.get("easy_pct"),
        inten.get("moderate_pct"),
        inten.get("hard_pct"),
    )
    if easy is not None:
        if mod is not None and mod > 25:
            insights.append(
                {
                    "level": "warn",
                    "title": "Too much grey zone",
                    "text": f"Moderate (Z3) is {mod}% of your time. Polarise more: move some of it "
                    "to easy (Z1–Z2) or hard (Z4–Z6).",
                }
            )
        elif hard is not None and hard < 5 and easy > 85:
            insights.append(
                {
                    "level": "info",
                    "title": "Almost all easy",
                    "text": f"Only {hard}% hard work in the last 28 days. Add one quality session "
                    "(tempo or intervals) to stimulate fitness.",
                }
            )
        elif mod is not None and hard is not None and 70 <= easy <= 88 and mod <= 15:
            insights.append(
                {
                    "level": "good",
                    "title": "Polarised like a pro",
                    "text": f"Easy {easy}% / moderate {mod}% / hard {hard}% — close to the 80/20 ideal.",
                }
            )

    load = snapshot.get("load") or {}
    last7, prev7 = load.get("last_7d"), load.get("prev_7d")
    if last7 is not None and prev7 and prev7 > 0:
        ratio = last7 / prev7
        if ratio > 1.3:
            insights.append(
                {
                    "level": "warn",
                    "title": "Big week-on-week jump",
                    "text": f"This week's load is {round((ratio - 1) * 100)}% above last week. Cap "
                    "progression near 10% to stay injury-free.",
                }
            )

    for s in snapshot.get("shoes") or []:
        km, thr = s.get("km"), s.get("threshold_km")
        if km is not None and thr and not s.get("retired") and km >= thr:
            insights.append(
                {
                    "level": "warn",
                    "title": f"Shoe due for replacement: {s.get('name')}",
                    "text": f"{km} km logged against a {thr:.0f} km threshold.",
                }
            )

    days_since = load.get("days_since_last_run")
    if days_since is not None and days_since >= 7:
        insights.append(
            {
                "level": "info",
                "title": "Training gap",
                "text": f"It has been {days_since} days since your last run. Ease back in with an "
                "easy session before adding intensity.",
            }
        )

    vo2 = snapshot.get("vo2max") or {}
    if vo2.get("effective"):
        insights.append(
            {
                "level": "info",
                "title": "Current aerobic ceiling",
                "text": f"Effective VO2max ≈ {vo2['effective']} ml/kg/min (Daniels VDOT). Use the "
                "race predictor table for goal pacing.",
            }
        )

    # Pain recurrence and prevention work (post-run feedback + support sessions).
    wellness = snapshot.get("wellness") or {}
    pain_runs = wellness.get("pain_runs_10") or 0
    if pain_runs >= 2:
        locs = ", ".join(wellness.get("pain_locations_10") or [])
        worsening = wellness.get("pain_worsening_10") or 0
        text = f"Pain was reported in {pain_runs} of your last 10 runs"
        if locs:
            text += f" ({locs})"
        if worsening:
            text += f", worsening in {worsening}"
        text += ". Prioritise mobility/strength and consider an easy week or a professional assessment."
        insights.append({"level": "warn", "title": "Recurring pain", "text": text})

    readiness = wellness.get("readiness_avg_10")
    if readiness is not None and readiness <= 2.5:
        insights.append(
            {
                "level": "warn",
                "title": "Low readiness",
                "text": f"Average pre-run readiness is {readiness}/5 over your last runs. "
                "Reduce intensity and protect sleep before adding load.",
            }
        )

    support = snapshot.get("support") or {}
    strength_7d = support.get("strength_7d")
    mobility_7d = support.get("mobility_7d")
    if pain_runs >= 1 and (strength_7d == 0 or mobility_7d == 0):
        insights.append(
            {
                "level": "info",
                "title": "Prevention work is light",
                "text": f"Strength sessions this week: {strength_7d or 0}, mobility: {mobility_7d or 0}. "
                "Add 1–2 short sessions to support the painful area.",
            }
        )
    elif support.get("sessions_7d", 0) >= 3:
        insights.append(
            {
                "level": "good",
                "title": "Durability work on track",
                "text": f"{support.get('sessions_7d')} support sessions this week "
                f"({strength_7d or 0} strength, {mobility_7d or 0} mobility).",
            }
        )

    # Fuel & recovery (context only — never prescriptive).
    nutrition = snapshot.get("nutrition") or {}
    weight = nutrition.get("weight") or {}
    per_week = weight.get("pct_per_week")
    if per_week is not None and per_week <= -WEIGHT_LOSS_WARN_PCT_PER_WEEK:
        insights.append(
            {
                "level": "warn",
                "title": "Rapid weight loss",
                "text": f"You are losing about {abs(per_week):.1f}% of body weight per week. "
                "Rapid loss can hurt performance and increase injury/illness risk — fuel "
                "adequately and consider professional advice.",
            }
        )

    energy = nutrition.get("energy_avg")
    if energy is not None and energy <= 2.0:
        insights.append(
            {
                "level": "info",
                "title": "Low energy",
                "text": f"Average energy is {energy}/5 this week. Check fueling, hydration and "
                "recovery before adding training load.",
            }
        )

    steps_avg = nutrition.get("steps_avg_7d")
    if steps_avg is not None and steps_avg < STEPS_SEDENTARY_WARN:
        band = (snapshot.get("acwr") or {}).get("band")
        extra = ""
        if band in ("ramping_up", "sharp_increase"):
            extra = " Combined with your rising training load, this raises injury risk."
        level = (
            "warn"
            if (
                steps_avg < STEPS_SEDENTARY_HIGH
                or band in ("ramping_up", "sharp_increase")
            )
            else "info"
        )
        insights.append(
            {
                "level": level,
                "title": "Low daily activity (sedentary)",
                "text": f"Average {round(steps_avg)} steps/day this week. Low daily movement is "
                "associated with higher injury risk; add easy walking on rest days."
                + extra,
            }
        )

    if nutrition.get("logs_7d", 0) >= 3:
        rarely = [
            s
            for s in (nutrition.get("supplements") or [])
            if s.get("taken_days_7d", 0) <= 1
        ]
        if rarely:
            names = ", ".join(s["name"] for s in rarely)
            insights.append(
                {
                    "level": "info",
                    "title": "Supplement adherence",
                    "text": f"Rarely taken this week: {names}. This is adherence tracking only — "
                    "no efficacy or dosing advice.",
                }
            )

    return insights
