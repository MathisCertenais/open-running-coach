"""Injury episodes and their link to strength work.

The athlete already reports pain, location, side and severity in the post-run
check-in. Storing injuries a second time in their own table would create two
sources of truth that drift, so an **episode is derived**: consecutive reports of
pain in the same place, less than `INJURY_EPISODE_GAP_DAYS` apart, form one
episode.

The correlation is deliberately conservative and explicitly *not* causal. It
answers one question: "was there a hard session loading these muscles in the
48 hours before this pain was first reported?" — and it names the exercises and
the matched keyword so the athlete can judge it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from .config import (
    INJURY_ACTIVE_DAYS,
    INJURY_EPISODE_GAP_DAYS,
    INJURY_LOOKBACK_HOURS,
    INJURY_SESSION_MIN_RPE,
)
from .exercises import LOWER_LIMB_PAIN, exercises_loading, muscles_for_pain


def _to_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def build_episodes(
    feedback: dict[str, dict],
    activity_dates: dict[str, str],
    today: date | None = None,
) -> list[dict]:
    """Group pain reports into episodes.

    ``feedback`` maps activity id to its post-run feedback; ``activity_dates``
    maps activity id to its ISO start date. Reports without a date are ignored:
    an episode without a timeline cannot be correlated with anything.
    """
    today = today or date.today()

    reports: list[dict] = []
    for activity_id, entry in feedback.items():
        if not entry.get("pain"):
            continue
        day = _to_date(activity_dates.get(activity_id))
        if day is None:
            continue
        reports.append(
            {
                "activity_id": activity_id,
                "date": day,
                "location": (entry.get("pain_location") or "other").lower(),
                "side": (entry.get("pain_side") or "").lower(),
                "severity": entry.get("pain_severity"),
                "trend": entry.get("pain_trend") or "",
                "timing": entry.get("pain_timing") or "",
            }
        )

    if not reports:
        return []

    reports.sort(key=lambda r: r["date"])

    groups: dict[tuple[str, str], list[dict]] = {}
    for report in reports:
        groups.setdefault((report["location"], report["side"]), []).append(report)

    episodes: list[dict] = []
    for (location, side), items in groups.items():
        current: list[dict] = []
        for item in items:
            if current and (item["date"] - current[-1]["date"]).days > (
                INJURY_EPISODE_GAP_DAYS
            ):
                episodes.append(_episode(location, side, current, today))
                current = []
            current.append(item)
        if current:
            episodes.append(_episode(location, side, current, today))

    episodes.sort(key=lambda e: e["last_date"], reverse=True)
    return episodes


def _episode(location: str, side: str, items: list[dict], today: date) -> dict:
    severities = [i["severity"] for i in items if i.get("severity") is not None]
    last = items[-1]
    return {
        "location": location,
        "side": side,
        "first_date": items[0]["date"].isoformat(),
        "last_date": last["date"].isoformat(),
        "reports": len(items),
        "max_severity": max(severities) if severities else None,
        "last_severity": last.get("severity"),
        "last_trend": last.get("trend", ""),
        "timing": last.get("timing", ""),
        "activity_ids": [i["activity_id"] for i in items],
        "active": (today - last["date"]).days <= INJURY_ACTIVE_DAYS,
        "explainable": location in LOWER_LIMB_PAIN,
    }


def hard_session_base_rate(
    dates: list[date], horizon: date, lookback_days: int = 2
) -> float | None:
    """Share of days that had a qualifying session in the preceding window.

    This is the denominator the injury panel was missing: if a hard leg session
    falls before 45% of all days anyway, then finding one before your pain
    episode tells you nothing. Returns None when there is not enough history to
    say anything (less than two weeks).
    """
    if not dates:
        return None
    start = min(dates)
    days = (horizon - start).days + 1
    if days < 14:
        return None
    hits = 0
    for offset in range(days):
        day = start + timedelta(days=offset)
        if any(0 <= (day - session).days <= lookback_days for session in dates):
            hits += 1
    return round(hits / days, 3)


def link_sessions_to_episodes(
    episodes: list[dict],
    sessions: list[dict],
    lookback_hours: int = INJURY_LOOKBACK_HOURS,
    min_rpe: int = INJURY_SESSION_MIN_RPE,
    today: date | None = None,
    verdicts: dict[tuple[str, str, str], str] | None = None,
) -> dict:
    """Find hard sessions that loaded the muscles of a pain episode.

    Returns ``{"links": [...], "summary": {...}}``. A link is only produced for
    lower-limb pain locations, where the muscle mapping is meaningful, and only
    for completed sessions inside the lookback window. Sessions with no
    recorded exercises cannot contribute: the app does not guess what was done.

    The summary also reports the **base rate** — how often a qualifying session
    precedes an ordinary day — so the number can be read against chance rather
    than in isolation.
    """
    today = today or date.today()
    verdicts = verdicts or {}
    lookback_days = max(1, round(lookback_hours / 24))

    prepared = []
    for session in sessions:
        if (session.get("status") or "completed") != "completed":
            continue
        rpe = session.get("rpe")
        if rpe is None or rpe < min_rpe:
            continue
        exercises = session.get("exercises") or []
        if not exercises:
            continue
        day = _to_date(session.get("date"))
        if day is None:
            continue
        prepared.append({"session": session, "date": day})

    links: list[dict] = []
    for episode in episodes:
        episode["verdict"] = verdicts.get(
            (episode["location"], episode["side"], episode["first_date"])
        )
        first = _to_date(episode["first_date"])
        if first is None:
            continue

        # Everything that happened in the week before, linked or not: the
        # timeline is what makes the claim legible.
        episode["preceding"] = [
            {
                "date": candidate["session"].get("date"),
                "title": candidate["session"].get("title")
                or candidate["session"].get("kind"),
                "kind": candidate["session"].get("kind"),
                "rpe": candidate["session"].get("rpe"),
                "exercises": [
                    exercise.get("name")
                    for exercise in candidate["session"].get("exercises") or []
                ],
            }
            for candidate in sorted(prepared, key=lambda c: c["date"], reverse=True)
            if 0 <= (first - candidate["date"]).days <= 7
        ]

        if not episode.get("explainable"):
            continue
        muscles = muscles_for_pain(episode["location"])
        if not muscles:
            continue
        for candidate in prepared:
            gap = first - candidate["date"]
            if gap.days < 0 or gap.days > lookback_days:
                continue
            hits = exercises_loading(muscles, candidate["session"].get("exercises"))
            if not hits:
                continue
            session = candidate["session"]
            links.append(
                {
                    "location": episode["location"],
                    "side": episode["side"],
                    "pain_first_date": episode["first_date"],
                    "session_id": session.get("id"),
                    "session_date": session.get("date"),
                    "session_title": session.get("title") or session.get("kind"),
                    "session_rpe": session.get("rpe"),
                    "hours_before": gap.days * 24,
                    "exercises": [h["name"] for h in hits],
                    "matched_muscles": sorted({m for h in hits for m in h["muscles"]}),
                    "explanation": (
                        f"{' + '.join(h['name'] for h in hits)} loads "
                        f"{', '.join(sorted({m for h in hits for m in h['muscles']}))}"
                    ),
                }
            )

    episodes_lower = [e for e in episodes if e.get("explainable")]
    explained = len({link["pain_first_date"] for link in links})
    base_rate = hard_session_base_rate(
        sorted({candidate["date"] for candidate in prepared}),
        today,
        lookback_days=lookback_days,
    )
    observed = round(explained / len(episodes_lower), 3) if episodes_lower else None

    if base_rate is None or observed is None:
        reading = "not enough history to compare with chance"
    elif len(episodes_lower) < 3:
        reading = "too few episodes to compare with chance"
    elif observed >= max(0.5, base_rate * 1.5):
        reading = "more often than your usual weeks"
    else:
        reading = "no different from your usual weeks"

    return {
        "episodes": episodes,
        "links": links,
        "summary": {
            "episodes": len(episodes),
            "episodes_lower_limb": len(episodes_lower),
            "episodes_with_hard_session": explained,
            "observed_rate": observed,
            "base_rate": base_rate,
            "reading": reading,
            "sessions_involved": sorted({link["session_date"] for link in links}),
            "lookback_hours": lookback_hours,
            "min_rpe": min_rpe,
            "note": (
                "Correlation, not causation: a hard session loading the same "
                "muscles before the pain first appeared."
            ),
        },
    }
