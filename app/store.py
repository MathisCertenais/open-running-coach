"""Persistence for notes, goals, profile, weight, shoes, RPE and plans."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class Store:
    """Small SQLite access layer, with no external dependency."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    activity_id TEXT PRIMARY KEY,
                    note        TEXT NOT NULL DEFAULT '',
                    updated_at  TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS goals (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    period     TEXT NOT NULL,   -- weekly | monthly | yearly
                    metric     TEXT NOT NULL,   -- distance | time | elevation
                    target     REAL NOT NULL,   -- canonical unit (m, s, m)
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS profile (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS weights (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    date       TEXT NOT NULL,
                    weight_kg  REAL NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shoes (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    name         TEXT NOT NULL,
                    notes        TEXT NOT NULL DEFAULT '',
                    threshold_km REAL NOT NULL DEFAULT 600,
                    retired      INTEGER NOT NULL DEFAULT 0,
                    created_at   TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS activity_shoe (
                    activity_id TEXT PRIMARY KEY,
                    shoe_id     INTEGER NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS activity_rpe (
                    activity_id TEXT PRIMARY KEY,
                    rpe         INTEGER NOT NULL,
                    updated_at  TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS plans (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    name             TEXT NOT NULL,
                    goal_description TEXT NOT NULL DEFAULT '',
                    weeks            INTEGER NOT NULL,
                    data             TEXT NOT NULL,
                    created_at       TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS activity_feedback (
                    activity_id   TEXT PRIMARY KEY,
                    session_type  TEXT NOT NULL DEFAULT '',
                    surface       TEXT NOT NULL DEFAULT '',
                    completed     TEXT NOT NULL DEFAULT '',
                    readiness     INTEGER,
                    sleep_quality INTEGER,
                    stress        INTEGER,
                    legs          INTEGER,
                    pain          INTEGER NOT NULL DEFAULT 0,
                    pain_location TEXT NOT NULL DEFAULT '',
                    pain_side     TEXT NOT NULL DEFAULT '',
                    pain_severity INTEGER,
                    pain_timing   TEXT NOT NULL DEFAULT '',
                    pain_trend    TEXT NOT NULL DEFAULT '',
                    is_race       INTEGER NOT NULL DEFAULT 0,
                    extra         TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    date         TEXT NOT NULL,
                    time         TEXT NOT NULL DEFAULT '',
                    kind         TEXT NOT NULL,
                    title        TEXT NOT NULL DEFAULT '',
                    duration_min INTEGER,
                    rpe          INTEGER,
                    focus        TEXT NOT NULL DEFAULT '[]',
                    notes        TEXT NOT NULL DEFAULT '',
                    status       TEXT NOT NULL DEFAULT 'completed',
                    source       TEXT NOT NULL DEFAULT 'manual',
                    plan_id      INTEGER,
                    created_at   TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS supplements (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    name       TEXT NOT NULL,
                    dose       TEXT NOT NULL DEFAULT '',
                    frequency  TEXT NOT NULL DEFAULT 'daily',
                    active     INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS nutrition_log (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    date               TEXT NOT NULL UNIQUE,
                    hydration_l        REAL,
                    energy             INTEGER,
                    appetite           INTEGER,
                    steps              INTEGER,
                    fueling_before     INTEGER NOT NULL DEFAULT 0,
                    fueling_during     INTEGER NOT NULL DEFAULT 0,
                    fueling_after      INTEGER NOT NULL DEFAULT 0,
                    fueling_notes      TEXT NOT NULL DEFAULT '',
                    supplements_taken  TEXT NOT NULL DEFAULT '[]',
                    notes              TEXT NOT NULL DEFAULT '',
                    macros             TEXT NOT NULL DEFAULT '{}',
                    created_at         TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS file_imports (
                    path        TEXT PRIMARY KEY,
                    kind        TEXT NOT NULL,
                    mtime_ns    INTEGER NOT NULL,
                    size        INTEGER NOT NULL,
                    imported_at TEXT NOT NULL
                )
                """
            )
            # Lightweight migrations for databases created before these columns.
            self._ensure_column("nutrition_log", "macros", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column("nutrition_log", "steps", "INTEGER")

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        cols = [
            r["name"]
            for r in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        ]
        if column not in cols:
            with self._conn:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------
    def get_note(self, activity_id: str) -> str:
        row = self._conn.execute(
            "SELECT note FROM notes WHERE activity_id = ?", (activity_id,)
        ).fetchone()
        return row["note"] if row else ""

    def set_note(self, activity_id: str, note: str) -> None:
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO notes (activity_id, note, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(activity_id) DO UPDATE SET
                    note = excluded.note,
                    updated_at = excluded.updated_at
                """,
                (activity_id, note, updated_at),
            )

    def all_notes(self) -> dict[str, str]:
        rows = self._conn.execute("SELECT activity_id, note FROM notes").fetchall()
        return {r["activity_id"]: r["note"] for r in rows}

    # ------------------------------------------------------------------
    # Goals
    # ------------------------------------------------------------------
    def add_goal(self, period: str, metric: str, target: float) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO goals (period, metric, target, created_at) VALUES (?, ?, ?, ?)",
                (period, metric, target, created_at),
            )
        return cur.lastrowid

    def update_goal(
        self, goal_id: int, period: str, metric: str, target: float
    ) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE goals SET period = ?, metric = ?, target = ? WHERE id = ?",
                (period, metric, target, goal_id),
            )

    def delete_goal(self, goal_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))

    def list_goals(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, period, metric, target, created_at FROM goals ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------
    def get_profile(self) -> dict[str, str]:
        rows = self._conn.execute("SELECT key, value FROM profile").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def set_profile(self, values: dict[str, str]) -> None:
        with self._conn:
            for key, value in values.items():
                self._conn.execute(
                    """
                    INSERT INTO profile (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, str(value)),
                )

    # ------------------------------------------------------------------
    # Weight
    # ------------------------------------------------------------------
    def add_weight(self, date: str, weight_kg: float) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO weights (date, weight_kg, created_at) VALUES (?, ?, ?)",
                (date, weight_kg, created_at),
            )
        return cur.lastrowid

    def delete_weight(self, weight_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM weights WHERE id = ?", (weight_id,))

    def list_weights(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, date, weight_kg FROM weights ORDER BY date DESC, id DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Shoes
    # ------------------------------------------------------------------
    def add_shoe(self, name: str, notes: str, threshold_km: float) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO shoes (name, notes, threshold_km, created_at) VALUES (?, ?, ?, ?)",
                (name, notes, threshold_km, created_at),
            )
        return cur.lastrowid

    def update_shoe(
        self, shoe_id: int, name: str, notes: str, threshold_km: float, retired: int
    ) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE shoes SET name = ?, notes = ?, threshold_km = ?, retired = ? WHERE id = ?",
                (name, notes, threshold_km, retired, shoe_id),
            )

    def delete_shoe(self, shoe_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM shoes WHERE id = ?", (shoe_id,))
            self._conn.execute(
                "DELETE FROM activity_shoe WHERE shoe_id = ?", (shoe_id,)
            )

    def list_shoes(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, name, notes, threshold_km, retired, created_at FROM shoes ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Activity -> shoe assignment
    # ------------------------------------------------------------------
    def set_activity_shoe(self, activity_id: str, shoe_id: int | None) -> None:
        with self._conn:
            if shoe_id is None:
                self._conn.execute(
                    "DELETE FROM activity_shoe WHERE activity_id = ?", (activity_id,)
                )
            else:
                self._conn.execute(
                    """
                    INSERT INTO activity_shoe (activity_id, shoe_id) VALUES (?, ?)
                    ON CONFLICT(activity_id) DO UPDATE SET shoe_id = excluded.shoe_id
                    """,
                    (activity_id, shoe_id),
                )

    def get_activity_shoe(self, activity_id: str) -> int | None:
        row = self._conn.execute(
            "SELECT shoe_id FROM activity_shoe WHERE activity_id = ?", (activity_id,)
        ).fetchone()
        return row["shoe_id"] if row else None

    def activity_shoe_map(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT activity_id, shoe_id FROM activity_shoe"
        ).fetchall()
        return {r["activity_id"]: r["shoe_id"] for r in rows}

    # ------------------------------------------------------------------
    # RPE (session Rating of Perceived Exertion, Foster 1-10 scale)
    # ------------------------------------------------------------------
    def get_rpe(self, activity_id: str) -> Optional[int]:
        row = self._conn.execute(
            "SELECT rpe FROM activity_rpe WHERE activity_id = ?", (activity_id,)
        ).fetchone()
        return row["rpe"] if row else None

    def set_rpe(self, activity_id: str, rpe: Optional[int]) -> None:
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._conn:
            if rpe is None:
                self._conn.execute(
                    "DELETE FROM activity_rpe WHERE activity_id = ?", (activity_id,)
                )
            else:
                self._conn.execute(
                    """
                    INSERT INTO activity_rpe (activity_id, rpe, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(activity_id) DO UPDATE SET
                        rpe = excluded.rpe,
                        updated_at = excluded.updated_at
                    """,
                    (activity_id, rpe, updated_at),
                )

    def all_rpe(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT activity_id, rpe FROM activity_rpe"
        ).fetchall()
        return {r["activity_id"]: r["rpe"] for r in rows}

    # ------------------------------------------------------------------
    # Plans
    # ------------------------------------------------------------------
    def add_plan(self, name: str, goal_description: str, weeks: int, data: dict) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO plans (name, goal_description, weeks, data, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, goal_description, weeks, json.dumps(data), created_at),
            )
        return cur.lastrowid

    def get_plan(self, plan_id: int) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT id, name, goal_description, weeks, data, created_at FROM plans WHERE id = ?",
            (plan_id,),
        ).fetchone()
        if row is None:
            return None
        plan = dict(row)
        plan["data"] = json.loads(plan["data"])
        return plan

    def list_plans(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, name, goal_description, weeks, created_at FROM plans ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_plan(self, plan_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM sessions WHERE plan_id = ?", (plan_id,))
            self._conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))

    # ------------------------------------------------------------------
    # Activity feedback (post-run subjective enrichment)
    # ------------------------------------------------------------------
    def get_feedback(self, activity_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM activity_feedback WHERE activity_id = ?", (activity_id,)
        ).fetchone()
        return self._feedback_row(row) if row else None

    def set_feedback(self, activity_id: str, data: dict) -> None:
        values = (
            activity_id,
            data.get("session_type", "") or "",
            data.get("surface", "") or "",
            data.get("completed", "") or "",
            data.get("readiness"),
            data.get("sleep_quality"),
            data.get("stress"),
            data.get("legs"),
            1 if data.get("pain") else 0,
            data.get("pain_location", "") or "",
            data.get("pain_side", "") or "",
            data.get("pain_severity"),
            data.get("pain_timing", "") or "",
            data.get("pain_trend", "") or "",
            1 if data.get("is_race") else 0,
            json.dumps(data.get("extra") or {}),
        )
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO activity_feedback (
                    activity_id, session_type, surface, completed, readiness,
                    sleep_quality, stress, legs, pain, pain_location, pain_side,
                    pain_severity, pain_timing, pain_trend, is_race, extra
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(activity_id) DO UPDATE SET
                    session_type=excluded.session_type,
                    surface=excluded.surface,
                    completed=excluded.completed,
                    readiness=excluded.readiness,
                    sleep_quality=excluded.sleep_quality,
                    stress=excluded.stress,
                    legs=excluded.legs,
                    pain=excluded.pain,
                    pain_location=excluded.pain_location,
                    pain_side=excluded.pain_side,
                    pain_severity=excluded.pain_severity,
                    pain_timing=excluded.pain_timing,
                    pain_trend=excluded.pain_trend,
                    is_race=excluded.is_race,
                    extra=excluded.extra
                """,
                values,
            )

    def all_feedback(self) -> dict[str, dict]:
        rows = self._conn.execute("SELECT * FROM activity_feedback").fetchall()
        return {r["activity_id"]: self._feedback_row(r) for r in rows}

    @staticmethod
    def _feedback_row(row) -> dict:
        data = {k: row[k] for k in row.keys() if k != "activity_id"}
        try:
            data["extra"] = json.loads(data.get("extra") or "{}")
        except (ValueError, TypeError):
            data["extra"] = {}
        data["pain"] = bool(data.get("pain"))
        data["is_race"] = bool(data.get("is_race"))
        data["activity_id"] = row["activity_id"]
        return data

    # ------------------------------------------------------------------
    # Support sessions (strength, mobility, cross-training, rest)
    # ------------------------------------------------------------------
    def add_session(self, data: dict) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO sessions (
                    date, time, kind, title, duration_min, rpe, focus, notes,
                    status, source, plan_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("date", ""),
                    data.get("time", "") or "",
                    data.get("kind", "other"),
                    data.get("title", "") or "",
                    data.get("duration_min"),
                    data.get("rpe"),
                    json.dumps(data.get("focus") or []),
                    data.get("notes", "") or "",
                    data.get("status", "completed") or "completed",
                    data.get("source", "manual") or "manual",
                    data.get("plan_id"),
                    created_at,
                ),
            )
        return cur.lastrowid

    def update_session(self, session_id: int, data: dict) -> None:
        with self._conn:
            self._conn.execute(
                """
                UPDATE sessions SET
                    date = ?, time = ?, kind = ?, title = ?, duration_min = ?,
                    rpe = ?, focus = ?, notes = ?, status = ?
                WHERE id = ?
                """,
                (
                    data.get("date", ""),
                    data.get("time", "") or "",
                    data.get("kind", "other"),
                    data.get("title", "") or "",
                    data.get("duration_min"),
                    data.get("rpe"),
                    json.dumps(data.get("focus") or []),
                    data.get("notes", "") or "",
                    data.get("status", "completed") or "completed",
                    session_id,
                ),
            )

    def delete_session(self, session_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def get_session(self, session_id: int) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return self._session_row(row) if row else None

    def list_sessions(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        plan_id: Optional[int] = None,
    ) -> list[dict]:
        clauses = []
        params: list = []
        if date_from:
            clauses.append("date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("date <= ?")
            params.append(date_to)
        if plan_id is not None:
            clauses.append("plan_id = ?")
            params.append(plan_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM sessions {where} ORDER BY date, time, id", params
        ).fetchall()
        return [self._session_row(r) for r in rows]

    def delete_sessions_for_plan(self, plan_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM sessions WHERE plan_id = ?", (plan_id,))

    @staticmethod
    def _session_row(row) -> dict:
        data = dict(row)
        try:
            data["focus"] = json.loads(data.get("focus") or "[]")
        except (ValueError, TypeError):
            data["focus"] = []
        return data

    # ------------------------------------------------------------------
    # Supplements
    # ------------------------------------------------------------------
    def add_supplement(self, name: str, dose: str, frequency: str) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO supplements (name, dose, frequency, active, created_at)
                VALUES (?, ?, ?, 1, ?)
                """,
                (name, dose, frequency, created_at),
            )
        return cur.lastrowid

    def list_supplements(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, name, dose, frequency, active FROM supplements ORDER BY id"
        ).fetchall()
        return [self._supplement_row(r) for r in rows]

    def update_supplement(
        self, supplement_id: int, name: str, dose: str, frequency: str, active: bool
    ) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE supplements SET name = ?, dose = ?, frequency = ?, active = ? WHERE id = ?",
                (name, dose, frequency, 1 if active else 0, supplement_id),
            )

    def delete_supplement(self, supplement_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM supplements WHERE id = ?", (supplement_id,))

    @staticmethod
    def _supplement_row(row) -> dict:
        data = dict(row)
        data["active"] = bool(data.get("active"))
        return data

    # ------------------------------------------------------------------
    # Nutrition log (daily fuel & recovery check-in)
    # ------------------------------------------------------------------
    def upsert_nutrition(self, date_str: str, data: dict) -> Optional[dict]:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO nutrition_log (
                    date, hydration_l, energy, appetite, steps, fueling_before,
                    fueling_during, fueling_after, fueling_notes,
                    supplements_taken, notes, macros, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    hydration_l=excluded.hydration_l,
                    energy=excluded.energy,
                    appetite=excluded.appetite,
                    steps=excluded.steps,
                    fueling_before=excluded.fueling_before,
                    fueling_during=excluded.fueling_during,
                    fueling_after=excluded.fueling_after,
                    fueling_notes=excluded.fueling_notes,
                    supplements_taken=excluded.supplements_taken,
                    notes=excluded.notes,
                    macros=excluded.macros
                """,
                (
                    date_str,
                    data.get("hydration_l"),
                    data.get("energy"),
                    data.get("appetite"),
                    data.get("steps"),
                    1 if data.get("fueling_before") else 0,
                    1 if data.get("fueling_during") else 0,
                    1 if data.get("fueling_after") else 0,
                    data.get("fueling_notes", "") or "",
                    json.dumps(data.get("supplements_taken") or []),
                    data.get("notes", "") or "",
                    json.dumps(data.get("macros") or {}),
                    created_at,
                ),
            )
        return self.get_nutrition(date_str)

    def get_nutrition(self, date_str: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM nutrition_log WHERE date = ?", (date_str,)
        ).fetchone()
        return self._nutrition_row(row) if row else None

    def upsert_nutrition_macros(
        self, date_str: str, macros: dict, steps: Optional[int] = None
    ) -> None:
        """Set only macros/steps for a day, preserving manual check-in fields."""
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO nutrition_log (date, macros, steps, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    macros = excluded.macros,
                    steps = COALESCE(excluded.steps, nutrition_log.steps)
                """,
                (
                    date_str,
                    json.dumps(macros or {}),
                    steps,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def list_nutrition(
        self, date_from: Optional[str] = None, date_to: Optional[str] = None
    ) -> list[dict]:
        clauses = []
        params: list = []
        if date_from:
            clauses.append("date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("date <= ?")
            params.append(date_to)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM nutrition_log {where} ORDER BY date DESC", params
        ).fetchall()
        return [self._nutrition_row(r) for r in rows]

    def delete_nutrition(self, record_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM nutrition_log WHERE id = ?", (record_id,))

    @staticmethod
    def _nutrition_row(row) -> dict:
        data = dict(row)
        try:
            data["supplements_taken"] = json.loads(
                data.get("supplements_taken") or "[]"
            )
        except (ValueError, TypeError):
            data["supplements_taken"] = []
        try:
            data["macros"] = json.loads(data.get("macros") or "{}")
        except (ValueError, TypeError):
            data["macros"] = {}
        for key in ("fueling_before", "fueling_during", "fueling_after"):
            data[key] = bool(data.get(key))
        return data

    # ------------------------------------------------------------------
    # Imported files (connectors) and weight upsert
    # ------------------------------------------------------------------
    def is_file_imported(self, path: str, mtime_ns: int, size: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM file_imports WHERE path = ? AND mtime_ns = ? AND size = ?",
            (path, mtime_ns, size),
        ).fetchone()
        return row is not None

    def mark_file_imported(
        self, path: str, kind: str, mtime_ns: int, size: int
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO file_imports (path, kind, mtime_ns, size, imported_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    kind=excluded.kind,
                    mtime_ns=excluded.mtime_ns,
                    size=excluded.size,
                    imported_at=excluded.imported_at
                """,
                (path, kind, mtime_ns, size, datetime.now(timezone.utc).isoformat()),
            )

    def upsert_weight(self, date_str: str, weight_kg: float) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM weights WHERE date = ?", (date_str,))
            self._conn.execute(
                "INSERT INTO weights (date, weight_kg, created_at) VALUES (?, ?, ?)",
                (date_str, weight_kg, datetime.now(timezone.utc).isoformat()),
            )

    def delete_sessions_by_source(self, source: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM sessions WHERE source = ?", (source,))

    def close(self) -> None:
        self._conn.close()
