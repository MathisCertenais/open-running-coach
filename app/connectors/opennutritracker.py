"""Connector for OpenNutriTracker export bundles.

OpenNutriTracker (GPL-3; GitHub Releases / Google Play — not on F-Droid yet)
exports a ZIP containing either JSON files or CSV companions. We read the daily
totals (`user_tracked_day`) and the weight history (`weight_log`), which is
exactly what we need to link nutrition and weight to training.

Reference: https://github.com/simonoppowa/OpenNutriTracker/blob/main/docs/export-format.md
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path
from typing import Optional


def _first(row: dict, keys: tuple[str, ...]):
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _num(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _day(value) -> Optional[str]:
    if not value:
        return None
    text = str(value)[:10]
    return text if len(text) == 10 and text[4] == "-" else None


def read_export(path: Path) -> dict:
    """Return ``{nutrition: [...], weights: [...]}`` from an ONT export ZIP."""
    with zipfile.ZipFile(path) as zf:
        names = {name.split("/")[-1]: name for name in zf.namelist()}

        tracked: list[dict] = []
        if "user_tracked_day.json" in names:
            tracked = json.loads(
                zf.read(names["user_tracked_day.json"]).decode("utf-8")
            )
        elif "user_tracked_day.csv" in names:
            text = zf.read(names["user_tracked_day.csv"]).decode("utf-8")
            tracked = list(csv.DictReader(io.StringIO(text)))

        weight_rows: list[dict] = []
        if "weight_log.json" in names:
            try:
                weight_rows = json.loads(
                    zf.read(names["weight_log.json"]).decode("utf-8")
                )
            except (ValueError, UnicodeDecodeError):
                weight_rows = []

    nutrition = []
    for row in tracked:
        day = _day(_first(row, ("day", "date")))
        if not day:
            continue
        macros = {
            "calories": _num(
                _first(row, ("caloriesTracked", "calories_tracked", "calories", "kcal"))
            ),
            "protein_g": _num(
                _first(
                    row, ("proteinTracked", "protein_tracked", "protein", "proteins")
                )
            ),
            "carbs_g": _num(
                _first(row, ("carbsTracked", "carbs_tracked", "carbs", "carbohydrates"))
            ),
            "fat_g": _num(_first(row, ("fatTracked", "fat_tracked", "fat"))),
        }
        macros = {k: v for k, v in macros.items() if v is not None}
        if macros:
            nutrition.append({"date": day, "macros": macros})

    weights = []
    for row in weight_rows:
        if not isinstance(row, dict):
            continue
        day = _day(_first(row, ("date", "day")))
        kg = _num(_first(row, ("weight", "weightKg", "weight_kg", "value")))
        if day and kg:
            weights.append({"date": day, "weight_kg": kg})

    return {"nutrition": nutrition, "weights": weights}
