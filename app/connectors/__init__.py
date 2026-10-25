"""External data connectors (nutrition, workout).

Each domain has its own folder under data/. Files are imported once and
tracked in SQLite so a restart or a rescan does not duplicate data.
"""
from __future__ import annotations

from pathlib import Path

from . import generic, opennutritracker

NUTRITION_EXTENSIONS = (".zip", ".csv", ".json")
WORKOUT_EXTENSIONS = (".csv", ".json")


def import_nutrition_dir(store, directory: Path) -> dict:
    """Import new nutrition exports (daily macros and weight)."""
    stats = {"files": 0, "logs": 0, "weights": 0}
    if not directory or not directory.exists():
        return stats
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() not in NUTRITION_EXTENSIONS:
            continue
        stat = path.stat()
        if store.is_file_imported(str(path), stat.st_mtime_ns, stat.st_size):
            continue
        try:
            suffix = path.suffix.lower()
            if suffix == ".zip":
                data = opennutritracker.read_export(path)
            elif suffix == ".json":
                data = generic.read_nutrition_json(path)
            else:
                data = generic.read_nutrition_csv(path)
        except Exception:
            continue
        for log in data.get("nutrition", []):
            store.upsert_nutrition_macros(
                log["date"], log.get("macros") or {}, log.get("steps")
            )
            stats["logs"] += 1
        for weight in data.get("weights", []):
            store.upsert_weight(weight["date"], weight["weight_kg"])
            stats["weights"] += 1
        store.mark_file_imported(str(path), "nutrition", stat.st_mtime_ns, stat.st_size)
        stats["files"] += 1
    return stats


def import_workout_dir(store, directory: Path) -> dict:
    """Import new workout exports as support sessions."""
    stats = {"files": 0, "sessions": 0}
    if not directory or not directory.exists():
        return stats
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() not in WORKOUT_EXTENSIONS:
            continue
        stat = path.stat()
        if store.is_file_imported(str(path), stat.st_mtime_ns, stat.st_size):
            continue
        try:
            if path.suffix.lower() == ".json":
                sessions = generic.read_workout_json(path)
            else:
                sessions = generic.read_workout_csv(path)
        except Exception:
            continue
        source = f"import:{path.name}"
        store.delete_sessions_by_source(source)
        for session in sessions:
            store.add_session({**session, "source": source})
            stats["sessions"] += 1
        store.mark_file_imported(str(path), "workout", stat.st_mtime_ns, stat.st_size)
        stats["files"] += 1
    return stats


__all__ = [
    "import_nutrition_dir",
    "import_workout_dir",
    "generic",
    "opennutritracker",
]
