"""Validation and storage for files dropped into the UI.

Kept out of `main.py` so the rules can be tested without importing the FastAPI
app (which opens the database and creates the data folders at import time).

The contract is deliberately strict: a file must belong to a known category,
carry an extension that category's importer understands, be smaller than
`UPLOAD_MAX_BYTES`, and be **parsed successfully by the real importer** before it
replaces anything on disk.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from . import connectors as connectors_mod
from .config import UPLOAD_ALLOWED_EXTENSIONS, UPLOAD_DIRECTORIES, UPLOAD_MAX_BYTES
from .parsers import parse_file


class UploadError(Exception):
    """A rejected upload, carrying the HTTP status the API should return."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def check_category(category: str) -> None:
    """Raise unless the category is one the app can import."""
    if category not in UPLOAD_ALLOWED_EXTENSIONS:
        raise UploadError(404, f"Unknown category: {category}")


def sanitize_filename(raw: str) -> str:
    """Reduce a client-supplied name to a bare basename.

    A name containing a path (`../x.kmz`, `dir/x.kmz`) is rejected rather than
    silently cleaned, so a traversal attempt fails loudly.
    """
    candidate = (raw or "").strip()
    name = Path(candidate).name
    if not name or name != candidate or name.startswith("."):
        raise UploadError(400, "Invalid filename")
    return name


def check_extension(category: str, name: str) -> str:
    """Return the lower-case suffix, or raise if the category rejects it."""
    suffix = Path(name).suffix.lower()
    allowed = UPLOAD_ALLOWED_EXTENSIONS[category]
    label = suffix or "no extension"
    if suffix not in allowed:
        raise UploadError(
            415, f"{category} accepts {', '.join(allowed)} (received '{label}')"
        )
    return suffix


def validate_file(category: str, path: Path) -> bool:
    """True if the matching importer can read this file.

    Never raises: an unreadable file is a user mistake to report, not an
    internal error. The caller deletes the temp file either way.
    """
    suffix = path.suffix.lower()
    try:
        if category == "running":
            return parse_file(path) is not None
        if category == "nutrition":
            if suffix == ".zip":
                data = connectors_mod.opennutritracker.read_export(path)
            elif suffix == ".json":
                data = connectors_mod.generic.read_nutrition_json(path)
            else:
                data = connectors_mod.generic.read_nutrition_csv(path)
            return bool(data.get("nutrition") or data.get("weights"))
        if category == "workout":
            if suffix == ".json":
                return bool(connectors_mod.generic.read_workout_json(path))
            return bool(connectors_mod.generic.read_workout_csv(path))
    except Exception:
        # Documented fallback (CODING_STANDARDS rule 9): unreadable -> reject.
        return False
    return False


def rejection_message(category: str, suffix: str) -> str:
    """Explain what the category expected, in user terms."""
    hints = {
        "running": "an OpenTracks KMZ, a GPX, or a Garmin TCX activity file",
        "nutrition": "a nutrition export with daily rows: meals, steps or weight",
        "workout": "a workout export with dated sessions",
    }
    accepted = ", ".join(UPLOAD_ALLOWED_EXTENSIONS[category])
    return (
        f"The file was not recognised as {hints[category]}. "
        f"Accepted extensions: {accepted}."
    )


def store_upload(category: str, raw_filename: str, body: bytes) -> dict:
    """Validate an upload and atomically place it in its data folder.

    Returns a dict describing what was stored; raises :class:`UploadError` when
    the file is rejected. The file is written to a hidden temp path in the same
    directory first, so a rejected upload never replaces a good file, and the
    final move is atomic on the same filesystem.
    """
    check_category(category)
    name = sanitize_filename(raw_filename)
    suffix = check_extension(category, name)

    if not body:
        raise UploadError(400, "Empty file")
    if len(body) > UPLOAD_MAX_BYTES:
        raise UploadError(413, "File is too large")

    # Validate in a temporary file that carries the real extension, outside the
    # data folder, so a rejected upload never appears in a scan and parsers see
    # the extension they dispatch on.
    with tempfile.TemporaryDirectory(prefix="coach-upload-") as probe_dir:
        probe = Path(probe_dir) / name
        probe.write_bytes(body)
        if not validate_file(category, probe):
            raise UploadError(422, rejection_message(category, suffix))

    target_dir = UPLOAD_DIRECTORIES[category]
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / name
    temp = target_dir / f".{name}.upload"
    replaced = target.exists()

    try:
        temp.write_bytes(body)
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)

    return {
        "category": category,
        "filename": name,
        "path": target,
        "bytes": len(body),
        "replaced": replaced,
    }
