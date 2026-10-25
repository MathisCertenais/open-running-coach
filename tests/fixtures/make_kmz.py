"""KMZ writer shaped like an OpenTracks export.

OpenTracks-specific quirks reproduced here on purpose:

- a ``<MultiTrack>`` holding one ``<Track>`` per manual segment;
- parallel ``<when>`` and ``<coord>`` arrays plus ``SimpleArrayData`` arrays for
  speed and ``trackpoint_type``;
- **no** ``heartrate`` or ``cadence`` array, which is the current real-world
  situation even though the schema declares both.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from .track import Run

DOC_NAME = "Synthetic OpenTracks run"
DESCRIPTION = "Three laps, no heart rate"
TRACK_ID = "synthetic-opentracks-1"


def _track_xml(segment, lap_index: int, mark_idle: bool) -> str:
    whens: list[str] = []
    coords: list[str] = []
    speeds: list[str] = []
    types: list[str] = []

    for i, s in enumerate(segment):
        whens.append(f"<when>{s.t.strftime('%Y-%m-%dT%H:%M:%SZ')}</when>")
        coords.append(f"<coord>{s.lon:.7f} {s.lat:.7f} {s.ele:.1f}</coord>")
        speeds.append(f"<value>{s.speed:.3f}</value>")
        ptype = "TRACKPOINT"
        if i == 0:
            ptype = "SEGMENT_START_MANUAL"
        elif mark_idle and i == len(segment) - 1 and lap_index == 0:
            # An isolated IDLE sample at a traffic light.
            ptype = "IDLE"
        types.append(f"<value>{ptype}</value>")

    return (
        "<Track>"
        + "".join(whens)
        + "".join(coords)
        + '<ExtendedData><SchemaData schemaUrl="#schema">'
        + f'<SimpleArrayData name="speed">{"".join(speeds)}</SimpleArrayData>'
        + f'<SimpleArrayData name="trackpoint_type">{"".join(types)}'
        + "</SimpleArrayData>"
        + "</SchemaData></ExtendedData>"
        + "</Track>"
    )


def kml_text(run: Run, mark_idle: bool = True) -> str:
    """Return the KML document as a string."""
    tracks = "".join(
        _track_xml(seg, i, mark_idle) for i, seg in enumerate(run.segments)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.3" '
        'xmlns:ot="http://opentracksapp.com/xmlschemas/v1">'
        "<Document>"
        f"<name>{DOC_NAME}</name>"
        "<Placemark>"
        "<name>Track</name>"
        f"<ot:trackid>{TRACK_ID}</ot:trackid>"
        f"<description>{DESCRIPTION}</description>"
        '<ExtendedData><Data name="type"><value>running</value></Data></ExtendedData>'
        f"<MultiTrack>{tracks}</MultiTrack>"
        "</Placemark>"
        "</Document>"
        "</kml>"
    )


def write_kmz(path: Path, run: Run, mark_idle: bool = True) -> Path:
    """Write an OpenTracks-shaped KMZ to ``path`` and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", kml_text(run, mark_idle))
    return path


def write_synthetic_kmz(path: Path) -> Path:
    """Convenience wrapper: the canonical run as an OpenTracks KMZ."""
    from .track import build_run

    return write_kmz(path, build_run(with_sensors=False))
