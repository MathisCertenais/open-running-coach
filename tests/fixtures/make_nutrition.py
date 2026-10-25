"""Nutrition, weight and steps exports.

Two shapes, both accepted by the connector:

- ``Waistline`` style CSV: semicolon delimited, French headers with units in
  parentheses, decimal comma. This is the least friendly real-world input and
  the one the tolerant parser exists for.
- Generic JSON: a list of daily records with a ``macros`` object.
"""

from __future__ import annotations

import json
from pathlib import Path

# date; calories; protein; carbs; fat; weight; steps
CSV_ROWS = [
    ("20/10/2026", 2100, 120, 260, 70, "72,4", 2800),
    ("21/10/2026", 1950, 110, 240, 65, "72,0", 3500),
    ("22/10/2026", 2050, 115, 250, 68, "71,8", 2100),
]
CSV_HEADER = (
    "Date;Calories (kcal);Protéines (g);Glucides (g);Lipides (g);Poids (kg);Pas"
)

JSON_DAYS = [
    {
        "date": "2026-10-20",
        "macros": {"calories": 2100, "protein_g": 120, "carbs_g": 260, "fat_g": 70},
        "steps": 2800,
        "weight_kg": 72.4,
    },
    {
        "date": "2026-10-21",
        "macros": {"calories": 1950, "protein_g": 110, "carbs_g": 240, "fat_g": 65},
        "steps": 3500,
        "weight_kg": 72.0,
    },
]


def nutrition_csv_text() -> str:
    lines = [CSV_HEADER]
    for day, kcal, protein, carbs, fat, weight, steps in CSV_ROWS:
        lines.append(f"{day};{kcal};{protein};{carbs};{fat};{weight};{steps}")
    return "\n".join(lines) + "\n"


def write_nutrition_csv(path: Path) -> Path:
    """Write a Waistline-shaped CSV export and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(nutrition_csv_text(), encoding="utf-8-sig")
    return path


def write_nutrition_json(path: Path) -> Path:
    """Write a generic JSON nutrition export and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"nutrition": JSON_DAYS}, indent=2), encoding="utf-8")
    return path
