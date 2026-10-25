"""Parser for KMZ files (OpenTracks format).

A KMZ is a ZIP archive containing a KML file (`doc.kml`). This module extracts
the GPS trackpoints and metadata of each activity.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

from .model import Activity, Marker, TrackPoint, _children, _child, _text, _local, _normalize_type, _parse_float, _parse_iso

# KML coordinate order is "longitude latitude altitude".
# Namespaces vary with the KML version.
_KML_NS = "{http://www.opengis.net/kml/2.3}"
_OPENTRACKS_NS = "{http://opentracksapp.com/xmlschemas/v1}"


def _parse_track(track_elem: ET.Element) -> list[TrackPoint]:
    """Parse a <Track> element into a list of TrackPoint (parallel arrays)."""
    whens = [_text(w) for w in _children(track_elem, "when")]
    coords = [_text(c) for c in _children(track_elem, "coord")]

    # Extended data arrays (speed, hr, cadence, ...) indexed like `when`.
    arrays: dict[str, list[Optional[str]]] = {}
    for ext in _children(track_elem, "ExtendedData"):
        for schema in _children(ext, "SchemaData"):
            for sda in _children(schema, "SimpleArrayData"):
                name = sda.get("name")
                if name is None:
                    continue
                arrays[name] = [_text(v) for v in _children(sda, "value")]

    def arr(name: str) -> list[Optional[str]]:
        return arrays.get(name, [])

    speeds = arr("speed")
    hrs = arr("heartrate")
    cads = arr("cadence")
    ptypes = arr("trackpoint_type")

    n = len(whens)
    points: list[TrackPoint] = []
    for i in range(n):
        coord = coords[i] if i < len(coords) else None
        lat = lon = ele = None
        if coord and coord.strip():
            parts = coord.split()
            if len(parts) >= 2:
                lon = _parse_float(parts[0])
                lat = _parse_float(parts[1])
            if len(parts) >= 3:
                ele = _parse_float(parts[2])

        points.append(TrackPoint(
            lat=lat, lon=lon, ele=ele,
            time=_parse_iso(whens[i]),
            speed=_parse_float(speeds[i]) if i < len(speeds) else None,
            hr=_parse_float(hrs[i]) if i < len(hrs) else None,
            cadence=_parse_float(cads[i]) if i < len(cads) else None,
            ptype=ptypes[i] if i < len(ptypes) else None,
        ))
    return points


def _parse_marker(placemark: ET.Element) -> Optional[Marker]:
    """Parse a point-type <Placemark> (waypoint)."""
    point = _child(placemark, "Point")
    if point is None:
        return None
    coord_el = _child(point, "coordinates")
    coord = _text(coord_el)
    if not coord:
        return None
    parts = coord.split(",")
    lat = lon = None
    ele = None
    if len(parts) >= 2:
        lon = _parse_float(parts[0])
        lat = _parse_float(parts[1])
    if len(parts) >= 3:
        ele = _parse_float(parts[2])

    ts = _child(placemark, "TimeStamp")
    when = _text(_child(ts, "when")) if ts is not None else None

    return Marker(
        lat=lat, lon=lon, ele=ele,
        name=_text(_child(placemark, "name")),
        description=_text(_child(placemark, "description")),
        time=_parse_iso(when),
    )


def parse_kmz(path: Path) -> Optional[Activity]:
    """Parse a KMZ file into an Activity, or return None if invalid."""
    try:
        with zipfile.ZipFile(path) as zf:
            kml_names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
            if not kml_names:
                return None
            # Prefer doc.kml
            kml_name = "doc.kml" if "doc.kml" in kml_names else kml_names[0]
            kml_data = zf.read(kml_name)
    except (zipfile.BadZipFile, OSError):
        return None

    try:
        root = ET.fromstring(kml_data)
    except ET.ParseError:
        return None

    document = root
    if _local(root.tag) != "Document":
        document = _child(root, "Document") or root

    doc_name = _text(_child(document, "name"))
    trackid = None
    description = None
    activity_type_raw = "unknown"
    track_placemark = None
    markers: list[Marker] = []

    for pm in _children(document, "Placemark"):
        multitrack = _child(pm, "MultiTrack")
        if multitrack is not None:
            track_placemark = pm
            tid_el = pm.find(f"{_OPENTRACKS_NS}trackid")
            if tid_el is not None:
                trackid = _text(tid_el)
            description = _text(_child(pm, "description"))
            for ext in _children(pm, "ExtendedData"):
                for data in _children(ext, "Data"):
                    if data.get("name") == "type":
                        activity_type_raw = _text(_child(data, "value")) or "unknown"
                        break
            continue

        marker = _parse_marker(pm)
        if marker is not None:
            markers.append(marker)

    if track_placemark is None:
        return None

    points: list[TrackPoint] = []
    segments: list[list[TrackPoint]] = []
    multitrack = _child(track_placemark, "MultiTrack")
    for track in _children(multitrack, "Track"):
        seg_pts = _parse_track(track)
        points.extend(seg_pts)
        segments.append(seg_pts)

    if not trackid:
        trackid = path.stem

    return Activity(
        id=trackid,
        filename=path.name,
        name=doc_name or path.stem,
        description=description,
        activity_type=_normalize_type(activity_type_raw),
        activity_type_raw=activity_type_raw,
        points=points,
        segments=segments,
        markers=markers,
    )
