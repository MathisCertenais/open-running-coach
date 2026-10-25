"""Tests for upload validation and storage (the drag-and-drop endpoint rules).

`app/uploads.py` is deliberately free of FastAPI and database access so these
tests run without booting the app or touching `coach.db`.
"""

from __future__ import annotations

import pytest

from app import uploads
from app.config import UPLOAD_ALLOWED_EXTENSIONS
from tests.fixtures.make_gpx import gpx_text
from tests.fixtures.make_kmz import kml_text
from tests.fixtures.make_nutrition import nutrition_csv_text
from tests.fixtures.make_tcx import tcx_text
from tests.fixtures.make_workout import workout_json_text
from tests.fixtures.track import build_run


def gpx_bytes() -> bytes:
    return gpx_text(build_run()).encode("utf-8")


# ---------------------------------------------------------------------------
# Filenames
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name", ["../../etc/passwd.kmz", "sub/dir/run.kmz", "..\\run.kmz", ""]
)
def test_path_like_filenames_are_rejected(name):
    with pytest.raises(uploads.UploadError) as exc:
        uploads.sanitize_filename(name)

    assert exc.value.status == 400


def test_hidden_filenames_are_rejected():
    with pytest.raises(uploads.UploadError):
        uploads.sanitize_filename(".env")


def test_a_plain_name_is_kept():
    assert uploads.sanitize_filename("  run.kmz  ") == "run.kmz"


# ---------------------------------------------------------------------------
# Extensions per category
# ---------------------------------------------------------------------------
def test_running_rejects_formats_it_cannot_parse():
    with pytest.raises(uploads.UploadError) as exc:
        uploads.check_extension("running", "notes.txt")

    assert exc.value.status == 415
    assert ".kmz" in exc.value.message


@pytest.mark.parametrize(
    "category, name",
    [
        ("running", "run.kmz"),
        ("running", "run.gpx"),
        ("running", "run.tcx"),
        ("nutrition", "days.csv"),
        ("nutrition", "export.json"),
        ("nutrition", "export.zip"),
        ("workout", "sessions.csv"),
        ("workout", "wger.json"),
    ],
)
def test_accepted_extensions(category, name):
    assert (
        uploads.check_extension(category, name) in UPLOAD_ALLOWED_EXTENSIONS[category]
    )


def test_unknown_category_is_rejected():
    with pytest.raises(uploads.UploadError) as exc:
        uploads.check_category("photos")

    assert exc.value.status == 404


# ---------------------------------------------------------------------------
# Content validation
# ---------------------------------------------------------------------------
def test_a_valid_gpx_is_accepted(tmp_path):
    path = tmp_path / "run.gpx"
    path.write_bytes(gpx_bytes())

    assert uploads.validate_file("running", path) is True


def test_a_valid_tcx_is_accepted(tmp_path):
    path = tmp_path / "run.tcx"
    path.write_bytes(tcx_text(build_run()).encode("utf-8"))

    assert uploads.validate_file("running", path) is True


def test_a_valid_kmz_is_accepted(tmp_path):
    import zipfile

    path = tmp_path / "run.kmz"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("doc.kml", kml_text(build_run()))

    assert uploads.validate_file("running", path) is True


def test_garbage_named_as_a_gpx_is_rejected(tmp_path):
    path = tmp_path / "run.gpx"
    path.write_bytes(b"not xml at all")

    assert uploads.validate_file("running", path) is False


def test_a_nutrition_csv_is_accepted(tmp_path):
    path = tmp_path / "days.csv"
    path.write_text(nutrition_csv_text(), encoding="utf-8")

    assert uploads.validate_file("nutrition", path) is True


def test_a_workout_json_is_accepted(tmp_path):
    path = tmp_path / "wger.json"
    path.write_text(workout_json_text(), encoding="utf-8")

    assert uploads.validate_file("workout", path) is True


def test_a_csv_full_of_nothing_is_rejected(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("date\n", encoding="utf-8")

    assert uploads.validate_file("nutrition", path) is False


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def test_storing_an_upload_writes_the_file(monkeypatch, tmp_path):
    monkeypatch.setitem(uploads.UPLOAD_DIRECTORIES, "running", tmp_path)

    stored = uploads.store_upload("running", "morning-run.gpx", gpx_bytes())

    assert stored["filename"] == "morning-run.gpx"
    assert stored["replaced"] is False
    assert (tmp_path / "morning-run.gpx").read_bytes() == gpx_bytes()
    # No temp file is left behind.
    assert [p.name for p in tmp_path.iterdir()] == ["morning-run.gpx"]


def test_reuploading_the_same_name_replaces_the_file(monkeypatch, tmp_path):
    monkeypatch.setitem(uploads.UPLOAD_DIRECTORIES, "running", tmp_path)
    uploads.store_upload("running", "run.gpx", gpx_bytes())

    second = uploads.store_upload("running", "run.gpx", gpx_bytes())

    assert second["replaced"] is True
    assert len(list(tmp_path.iterdir())) == 1


def test_a_rejected_upload_leaves_the_previous_file_intact(monkeypatch, tmp_path):
    monkeypatch.setitem(uploads.UPLOAD_DIRECTORIES, "running", tmp_path)
    uploads.store_upload("running", "run.gpx", gpx_bytes())
    original = (tmp_path / "run.gpx").read_bytes()

    with pytest.raises(uploads.UploadError) as exc:
        uploads.store_upload("running", "run.gpx", b"corrupted")

    assert exc.value.status == 422
    assert (tmp_path / "run.gpx").read_bytes() == original
    assert [p.name for p in tmp_path.iterdir()] == ["run.gpx"]


def test_empty_bodies_are_rejected(monkeypatch, tmp_path):
    monkeypatch.setitem(uploads.UPLOAD_DIRECTORIES, "running", tmp_path)

    with pytest.raises(uploads.UploadError) as exc:
        uploads.store_upload("running", "run.gpx", b"")

    assert exc.value.status == 400


def test_oversized_files_are_rejected(monkeypatch, tmp_path):
    monkeypatch.setitem(uploads.UPLOAD_DIRECTORIES, "running", tmp_path)
    monkeypatch.setattr(uploads, "UPLOAD_MAX_BYTES", 16)

    with pytest.raises(uploads.UploadError) as exc:
        uploads.store_upload("running", "run.gpx", b"x" * 32)

    assert exc.value.status == 413
    assert list(tmp_path.iterdir()) == []
