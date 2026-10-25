"""Parser for TCX files (Garmin Training Center XML).

TCX has explicit <Lap> elements, which map directly to the app's segments.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

from .model import (
    Activity,
    TrackPoint,
    _children,
    _child,
    _find_text,
    _local,
    _normalize_type,
    _parse_float,
    _parse_iso,
    _text,
    derive_id,
)


def _map_tcx_sport(raw: Optional[str]) -> str:
    if not raw:
        return "unknown"
    # "TrailRunning" -> "Trail_Running" so _normalize_type recognizes it.
    key = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", raw.strip())
    return _normalize_type(key)


def _parse_trackpoint(tp: ET.Element) -> TrackPoint:
    time = _parse_iso(_text(_child(tp, "Time")))

    pos = _child(tp, "Position")
    lat = lon = None
    if pos is not None:
        lat = _parse_float(_text(_child(pos, "LatitudeDegrees")))
        lon = _parse_float(_text(_child(pos, "LongitudeDegrees")))

    ele = _parse_float(_text(_child(tp, "AltitudeMeters")))

    hr_el = _child(tp, "HeartRateBpm")
    hr = _parse_float(_text(_child(hr_el, "Value"))) if hr_el is not None else None

    cad = _parse_float(_text(_child(tp, "Cadence")))

    ext = _child(tp, "Extensions")
    spd = _parse_float(_find_text(ext, {"Speed"})) if ext is not None else None

    return TrackPoint(lat=lat, lon=lon, ele=ele, time=time, speed=spd, hr=hr, cadence=cad)


def parse_tcx(path: Path) -> Optional[Activity]:
    """Parse a TCX file into an Activity, or return None if invalid."""
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError):
        return None
    root = tree.getroot()
    if _local(root.tag) != "TrainingCenterDatabase":
        return None

    activities_el = _child(root, "Activities")
    act_el = _child(activities_el, "Activity") if activities_el is not None else None
    if act_el is None:
        return None

    sport_raw = act_el.get("Sport") or "unknown"

    points: list[TrackPoint] = []
    segments: list[list[TrackPoint]] = []
    for lap in _children(act_el, "Lap"):
        track = _child(lap, "Track")
        if track is None:
            continue
        seg_points = [_parse_trackpoint(tp) for tp in _children(track, "Trackpoint")]
        if seg_points:
            points.extend(seg_points)
            segments.append(seg_points)

    if not points:
        return None

    return Activity(
        id=derive_id("tcx", points[0].time),
        filename=path.name,
        name=path.stem,
        description=None,
        activity_type=_map_tcx_sport(sport_raw),
        activity_type_raw=sport_raw,
        points=points,
        segments=segments,
        markers=[],
    )
