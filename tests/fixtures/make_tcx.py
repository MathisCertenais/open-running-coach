"""TCX writer shaped like a Garmin export.

Garmin writes one ``<Lap>`` per manual lap, a ``Trackpoint`` per sample, heart
rate in ``HeartRateBpm/Value``, cadence as a bare ``Cadence`` and speed inside a
namespaced ``Extensions/TPX`` block.
"""

from __future__ import annotations

from pathlib import Path

from .track import Run, iso

TCX_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<TrainingCenterDatabase "
    'xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2" '
    'xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2">'
)

SPORT = "Running"


def tcx_text(run: Run, sport: str = SPORT) -> str:
    parts = [
        TCX_HEADER,
        "<Activities>",
        f'<Activity Sport="{sport}">',
        f"<Id>{iso(run.start)}</Id>",
    ]

    for segment in run.segments:
        distance = sum(s.speed for s in segment)  # 1 s sampling
        parts.append(f'<Lap StartTime="{iso(segment[0].t)}">')
        parts.append(f"<TotalTimeSeconds>{len(segment)}</TotalTimeSeconds>")
        parts.append(f"<DistanceMeters>{distance:.1f}</DistanceMeters>")
        parts.append("<Track>")
        for s in segment:
            body = [
                f"<Time>{iso(s.t)}</Time>",
                "<Position>"
                f"<LatitudeDegrees>{s.lat:.7f}</LatitudeDegrees>"
                f"<LongitudeDegrees>{s.lon:.7f}</LongitudeDegrees>"
                "</Position>",
                f"<AltitudeMeters>{s.ele:.1f}</AltitudeMeters>",
            ]
            if s.hr is not None:
                body.append(f"<HeartRateBpm><Value>{s.hr:.0f}</Value></HeartRateBpm>")
            if s.cadence is not None:
                body.append(f"<Cadence>{s.cadence:.0f}</Cadence>")
            body.append(
                "<Extensions><ns3:TPX>"
                f"<ns3:Speed>{s.speed:.3f}</ns3:Speed>"
                "</ns3:TPX></Extensions>"
            )
            parts.append("<Trackpoint>" + "".join(body) + "</Trackpoint>")
        parts.append("</Track></Lap>")

    parts.append("</Activity></Activities></TrainingCenterDatabase>")
    return "".join(parts)


def write_tcx(path: Path, run: Run, sport: str = SPORT) -> Path:
    """Write a Garmin-shaped TCX file and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tcx_text(run, sport), encoding="utf-8")
    return path
