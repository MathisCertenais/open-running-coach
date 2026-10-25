"""GPX writer shaped like a Strava export.

Strava writes a numeric activity code in ``<type>`` (9 = running, 12 = trail
running), a ``<trkseg>`` per lap, and no speed sensor: pace has to be derived
from the positions. Heart rate and cadence live in a nested
``gpxtpx:TrackPointExtension``, which is exactly the namespace nesting the
parser must cope with.
"""

from __future__ import annotations

from pathlib import Path

from .track import Run, iso

GPX_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<gpx version="1.1" creator="StravaGPX" '
    'xmlns="http://www.topografix.com/GPX/1/1" '
    'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">'
)

NAME = "Morning Run"
DESCRIPTION = "Synthetic Strava-shaped export"


def gpx_text(run: Run, strava_type: str = "9", name: str = NAME) -> str:
    parts = [
        GPX_HEADER,
        f"<metadata><time>{iso(run.start)}</time></metadata>",
        "<trk>",
        f"<name>{name}</name>",
        f"<type>{strava_type}</type>",
        f"<desc>{DESCRIPTION}</desc>",
    ]
    for segment in run.segments:
        parts.append("<trkseg>")
        for s in segment:
            extensions = ""
            if s.hr is not None or s.cadence is not None:
                inner = ""
                if s.hr is not None:
                    inner += f"<gpxtpx:hr>{s.hr:.0f}</gpxtpx:hr>"
                if s.cadence is not None:
                    inner += f"<gpxtpx:cad>{s.cadence:.0f}</gpxtpx:cad>"
                extensions = (
                    "<extensions><gpxtpx:TrackPointExtension>"
                    f"{inner}"
                    "</gpxtpx:TrackPointExtension></extensions>"
                )
            parts.append(
                f'<trkpt lat="{s.lat:.7f}" lon="{s.lon:.7f}">'
                f"<ele>{s.ele:.1f}</ele><time>{iso(s.t)}</time>"
                f"{extensions}</trkpt>"
            )
        parts.append("</trkseg>")
    parts.append("</trk></gpx>")
    return "".join(parts)


def write_gpx(path: Path, run: Run, strava_type: str = "9") -> Path:
    """Write a Strava-shaped GPX file and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(gpx_text(run, strava_type), encoding="utf-8")
    return path
