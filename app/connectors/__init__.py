"""External data connectors (nutrition, workout).

Each domain has its own folder under data/. Files are imported once and
tracked in SQLite so a restart or a rescan does not duplicate data.
"""

from __future__ import annotations

from pathlib import Path

from ..config import DATA_NUTRITION_DIR, DATA_WORKOUT_DIR
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


def import_wger(
    store,
    token: str,
    base_url=None,
    nutrition_dir: Path = DATA_NUTRITION_DIR,
    workout_dir: Path = DATA_WORKOUT_DIR,
    transport=None,
    on_refresh=None,
) -> dict:
    """Pull wger once, write the exports and import them.

    One request per athlete action, never a poll (ADR-0008). The pull is
    read-only, and the files it writes go through the same connectors as a hand
    dropped export, so the result is replace-or-update, not append (ADR-0004).
    """
    # Imported here so `python -m app.connectors.wger_api` does not load itself
    # twice, and so the module is only touched when the pull is asked for.
    from . import wger_api

    client = wger_api.WgerClient(
        token,
        base_url=base_url or wger_api.base_url_from_env(),
        transport=transport,
        on_refresh=on_refresh or wger_api.store_token,
    )
    result = wger_api.pull(client)
    wger_api.write_exports(result, nutrition_dir, workout_dir)
    return {
        "pulled": result.stats,
        "nutrition": import_nutrition_dir(store, nutrition_dir),
        "workout": import_workout_dir(store, workout_dir),
    }


__all__ = [
    "import_nutrition_dir",
    "import_workout_dir",
    "import_wger",
    "generic",
    "opennutritracker",
]
