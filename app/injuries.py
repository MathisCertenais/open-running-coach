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

from datetime import date, datetime

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


def link_sessions_to_episodes(
    episodes: list[dict],
    sessions: list[dict],
    lookback_hours: int = INJURY_LOOKBACK_HOURS,
    min_rpe: int = INJURY_SESSION_MIN_RPE,
) -> dict:
    """Find hard sessions that loaded the muscles of a pain episode.

    Returns ``{"links": [...], "summary": {...}}``. A link is only produced for
    lower-limb pain locations, where the muscle mapping is meaningful, and only
    for completed sessions inside the lookback window. Sessions with no
    recorded exercises cannot contribute: the app does not guess what was done.
    """
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
        if not episode.get("explainable"):
            continue
        muscles = muscles_for_pain(episode["location"])
        if not muscles:
            continue
        first = _to_date(episode["first_date"])
        if first is None:
            continue
        for candidate in prepared:
            gap = first - candidate["date"]
            if gap.days < 0 or gap.days > 2:
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

    explained = len({link["pain_first_date"] for link in links})
    episodes_lower = [e for e in episodes if e.get("explainable")]
    session_dates = sorted({link["session_date"] for link in links})
    return {
        "links": links,
        "summary": {
            "episodes": len(episodes),
            "episodes_lower_limb": len(episodes_lower),
            "episodes_with_hard_session": explained,
            "sessions_involved": session_dates,
            "lookback_hours": lookback_hours,
            "min_rpe": min_rpe,
            "note": (
                "Correlation, not causation: a hard session loading the same "
                "muscles before the pain first appeared."
            ),
        },
    }
