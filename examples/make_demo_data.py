"""Generate a complete synthetic dataset: activities, nutrition, weight, workouts.

Everything is produced from `tests/fixtures`, so nothing personal is involved.
Useful to try the app on a fresh clone, and used by the CI smoke job to boot the
server against real files.

Usage:
    .venv/bin/python examples/make_demo_data.py [data_dir]

Default target is `./data`. Restart the app afterwards (or press ↻) to import.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.fixtures.make_gpx import write_gpx  # noqa: E402
from tests.fixtures.make_kmz import write_kmz  # noqa: E402
from tests.fixtures.make_nutrition import write_nutrition_csv  # noqa: E402
from tests.fixtures.make_tcx import write_tcx  # noqa: E402
from tests.fixtures.make_workout import write_workout_json  # noqa: E402
from tests.fixtures.track import START, build_run  # noqa: E402

# (filename, writer, days before the canonical start date)
ACTIVITIES = [
    ("strava-recovery-run.gpx", "gpx", 0),
    ("garmin-tempo-run.tcx", "tcx", 2),
    ("opentracks-long-run.kmz", "kmz", 4),
    ("strava-easy-run-2.gpx", "gpx", 6),
    ("strava-intervals.gpx", "gpx", 9),
]

WRITERS = {"gpx": write_gpx, "tcx": write_tcx, "kmz": write_kmz}


def main(data_dir: Path | None = None) -> dict[str, int]:
    """Write the demo dataset and return a count per data folder."""
    data = Path(data_dir) if data_dir else ROOT / "data"

    written = {"running": 0, "nutrition": 0, "workout": 0}

    for filename, fmt, days_before in ACTIVITIES:
        run = build_run(start=START - timedelta(days=days_before))
        target = data / "running" / filename
        if fmt == "kmz":
            WRITERS[fmt](target, run, mark_idle=False)
        else:
            WRITERS[fmt](target, run)
        written["running"] += 1

    write_nutrition_csv(data / "nutrition" / "waistline-demo.csv")
    written["nutrition"] += 1

    write_workout_json(data / "workout" / "wger-demo.json")
    written["workout"] += 1

    return written


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    counts = main(target)
    print("Demo data written:")
    for folder, count in counts.items():
        print(f"  data/{folder}: {count} file(s)")
