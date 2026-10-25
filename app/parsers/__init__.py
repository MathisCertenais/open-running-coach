"""Activity parsers: each turns a file into an :class:`Activity` (or None).

The registry maps file extensions to parsers so the loader in main.py can scan
the data/ folder for every supported format.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .gpx import parse_gpx
from .kmz import parse_kmz
from .model import Activity, Marker, TrackPoint  # re-exported for convenience
from .tcx import parse_tcx

# extension (lowercase, with dot) -> parser callable
PARSERS = {
    ".kmz": parse_kmz,
    ".gpx": parse_gpx,
    ".tcx": parse_tcx,
}

SUPPORTED_EXTENSIONS = tuple(sorted(PARSERS.keys()))


def parse_file(path: Path) -> Optional[Activity]:
    """Parse a file with the parser matching its extension."""
    parser = PARSERS.get(path.suffix.lower())
    if parser is None:
        return None
    return parser(path)


__all__ = [
    "Activity",
    "Marker",
    "TrackPoint",
    "PARSERS",
    "SUPPORTED_EXTENSIONS",
    "parse_file",
    "parse_kmz",
    "parse_gpx",
    "parse_tcx",
]
