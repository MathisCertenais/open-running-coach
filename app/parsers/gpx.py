"""Parser for GPX files (Strava export and most other tools)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

from .model import (
    Activity,
    Marker,
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

# Strava writes its activity type as a numeric code in <type>.
_STRAVA_TYPE = {"9": "running", "12": "trail_running"}


def _map_gpx_type(raw: Optional[str]) -> str:
    if not raw:
        return "unknown"
    raw = raw.strip()
    if raw in _STRAVA_TYPE:
        return _STRAVA_TYPE[raw]
    return _normalize_type(raw)


def _parse_trkpt(trkpt: ET.Element) -> TrackPoint:
    lat = _parse_float(trkpt.get("lat"))
    lon = _parse_float(trkpt.get("lon"))
    ele = _parse_float(_text(_child(trkpt, "ele")))
    time = _parse_iso(_text(_child(trkpt, "time")))

    ext = _child(trkpt, "extensions")
    hr = _parse_float(_find_text(ext, {"hr", "heartrate"})) if ext is not None else None
    cad = _parse_float(_find_text(ext, {"cad", "cadence"})) if ext is not None else None
    spd = _parse_float(_find_text(ext, {"speed"})) if ext is not None else None

    return TrackPoint(lat=lat, lon=lon, ele=ele, time=time, speed=spd, hr=hr, cadence=cad)


def _parse_wpt(wpt: ET.Element) -> Optional[Marker]:
    lat = _parse_float(wpt.get("lat"))
    lon = _parse_float(wpt.get("lon"))
    if lat is None or lon is None:
        return None
    return Marker(
        lat=lat,
        lon=lon,
        ele=_parse_float(_text(_child(wpt, "ele"))),
        name=_text(_child(wpt, "name")),
        description=_text(_child(wpt, "desc")),
        time=_parse_iso(_text(_child(wpt, "time"))),
    )


def parse_gpx(path: Path) -> Optional[Activity]:
    """Parse a GPX file into an Activity, or return None if invalid."""
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError):
        return None
    root = tree.getroot()
    if _local(root.tag) != "gpx":
        return None

    points: list[TrackPoint] = []
    segments: list[list[TrackPoint]] = []
    markers: list[Marker] = []
    name = None
    description = None
    activity_type_raw = "unknown"

    for trk in _children(root, "trk"):
        if name is None:
            name = _text(_child(trk, "name"))
        if description is None:
            description = _text(_child(trk, "desc"))
        t = _text(_child(trk, "type"))
        if t:
            activity_type_raw = t
        for seg in _children(trk, "trkseg"):
            seg_points = [_parse_trkpt(tp) for tp in _children(seg, "trkpt")]
            if seg_points:
                points.extend(seg_points)
                segments.append(seg_points)

    for wpt in _children(root, "wpt"):
        marker = _parse_wpt(wpt)
        if marker is not None:
            markers.append(marker)

    if not points:
        return None

    return Activity(
        id=derive_id("gpx", points[0].time),
        filename=path.name,
        name=name or path.stem,
        description=description,
        activity_type=_map_gpx_type(activity_type_raw),
        activity_type_raw=activity_type_raw,
        points=points,
        segments=segments,
        markers=markers,
    )
