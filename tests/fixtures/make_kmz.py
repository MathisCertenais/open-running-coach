"""Generate synthetic OpenTracks KMZ files for parser tests.

The builder deliberately reproduces the quirks of real exports:

- several ``<Track>`` elements, i.e. several manual segments (laps);
- a ``trackpoint_type`` array containing ``IDLE`` and ``SEGMENT_START_MANUAL``;
- **no** ``heartrate`` or ``cadence`` array, which is the current real-world
  situation even though the schema declares them.
"""

from __future__ import annotations

import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

START = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)
LAT0, LON0 = 48.8566, 2.3522

# One lap, then a pause, then a second lap: this is what an interval session
# looks like when exported by OpenTracks.
LAPS = [
    {"points": 6, "speed": 2.5, "type": "SEGMENT_START_MANUAL"},
    {"points": 4, "speed": 4.0, "type": "TRACKPOINT"},
]

DOC_NAME = "Synthetic run"
DESCRIPTION = "Two laps, no heart rate"
TRACK_ID = "synthetic-1"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _track_xml(lap_index: int) -> str:
    lap = LAPS[lap_index]
    n = lap["points"]
    speed = lap["speed"]
    t = START + timedelta(minutes=10 * lap_index)
    # ~2 m per second eastwards, so the implied speed agrees with the sensor.
    lon = LON0 + lap_index * 0.001

    whens: list[str] = []
    coords: list[str] = []
    speeds: list[str] = []
    types: list[str] = []

    for i in range(n):
        whens.append(f"<when>{_iso(t)}</when>")
        coords.append(f"<coord>{lon:.7f} {LAT0:.7f} 35.0</coord>")
        speeds.append(f"<value>{speed:.2f}</value>")
        ptype = lap["type"] if i == 0 else "TRACKPOINT"
        if i == n - 1 and lap_index == 0:
            ptype = "IDLE"
        types.append(f"<value>{ptype}</value>")
        t += timedelta(seconds=1)
        lon += speed / (111_320.0 * 0.657)

    return (
        "<Track>"
        + "".join(whens)
        + "".join(coords)
        + '<ExtendedData><SchemaData schemaUrl="#schema">'
        + f'<SimpleArrayData name="speed">{"".join(speeds)}</SimpleArrayData>'
        + f'<SimpleArrayData name="trackpoint_type">{"".join(types)}</SimpleArrayData>'
        + "</SchemaData></ExtendedData>"
        + "</Track>"
    )


def kml_text() -> str:
    """Return the KML document as a string."""
    tracks = "".join(_track_xml(i) for i in range(len(LAPS)))
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


def write_synthetic_kmz(path: Path) -> Path:
    """Write a synthetic OpenTracks KMZ to ``path`` and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", kml_text())
    return path


if __name__ == "__main__":  # pragma: no cover - manual fixture generation
    import sys

    target = Path(sys.argv[1] if len(sys.argv) > 1 else "synthetic.kmz")
    print(write_synthetic_kmz(target))
