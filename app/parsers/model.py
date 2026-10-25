"""Shared data model and XML helpers for all activity parsers.

Every parser (KMZ, GPX, TCX, future FIT) returns an :class:`Activity`, so the
rest of the app is format-agnostic.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class TrackPoint:
    """A timestamped GPS point of an activity."""

    lat: Optional[float] = None
    lon: Optional[float] = None
    ele: Optional[float] = None
    time: Optional[datetime] = None
    speed: Optional[float] = None  # m/s
    hr: Optional[float] = None  # bpm
    cadence: Optional[float] = None  # rpm
    ptype: Optional[str] = None  # trackpoint type (TRACKPOINT, IDLE, ...)


@dataclass
class Marker:
    """A waypoint marker of an activity (e.g. a pause)."""

    lat: float = 0.0
    lon: float = 0.0
    ele: Optional[float] = None
    name: Optional[str] = None
    description: Optional[str] = None
    time: Optional[datetime] = None


@dataclass
class Activity:
    """A complete activity, parsed from a file."""

    id: str  # stable id (format-prefixed)
    filename: str
    name: str
    description: Optional[str]
    activity_type: str  # normalized
    activity_type_raw: str
    points: list[TrackPoint] = field(default_factory=list)
    segments: list[list[TrackPoint]] = field(default_factory=list)  # laps
    markers: list[Marker] = field(default_factory=list)

    @property
    def start_time(self) -> Optional[datetime]:
        for p in self.points:
            if p.time is not None:
                return p.time
        return None

    @property
    def end_time(self) -> Optional[datetime]:
        for p in reversed(self.points):
            if p.time is not None:
                return p.time
        return None


# ---------------------------------------------------------------------------
# XML helpers (shared by KMZ, GPX and TCX parsers)
# ---------------------------------------------------------------------------
def _local(tag: str) -> str:
    """Return the local name of a tag (without the namespace prefix)."""
    return tag.split("}", 1)[1] if "}" in tag else tag


def _children(elem: ET.Element, name: str) -> list[ET.Element]:
    """Return direct children whose local name equals `name`."""
    return [c for c in elem if _local(c.tag) == name]


def _child(elem: ET.Element, name: str) -> Optional[ET.Element]:
    found = _children(elem, name)
    return found[0] if found else None


def _text(elem: Optional[ET.Element]) -> Optional[str]:
    if elem is None:
        return None
    t = elem.text
    if t is None:
        return None
    t = t.strip()
    return t or None


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp (with or without a trailing 'Z')."""
    if not value:
        return None
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_float(value: Optional[str]) -> Optional[float]:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value.strip())
    except ValueError:
        return None


def _find_text(elem: Optional[ET.Element], names: set[str]) -> Optional[str]:
    """Return the text of the first descendant whose local name is in `names`.

    Used to read extension fields (hr, cadence, speed) regardless of their XML
    namespace.
    """
    if elem is None:
        return None
    for el in elem.iter():
        if _local(el.tag) in names:
            t = _text(el)
            if t is not None:
                return t
    return None


def _normalize_type(raw: Optional[str]) -> str:
    """Normalize an activity type to a canonical key."""
    if not raw:
        return "unknown"
    key = raw.strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "running": "running",
        "run": "running",
        "trail_running": "trail_running",
        "trail": "trail_running",
        "street_running": "street_running",
        "street": "street_running",
        "track_running": "track_running",
        "track": "track_running",
    }
    return mapping.get(key, "unknown")


def derive_id(prefix: str, start: Optional[datetime]) -> str:
    """Build a stable, format-prefixed id from the activity start time.

    Format-prefixing keeps KMZ UUIDs distinct from GPX/TCX ids, while the
    fingerprint dedup (in main.py) collapses duplicates across sources.
    """
    if start is None:
        return f"{prefix}:unknown"
    stamp = start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{prefix}:{stamp}"
