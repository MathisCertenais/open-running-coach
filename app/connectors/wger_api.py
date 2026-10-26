"""Opt-in pull from the wger REST API: weight, nutrition and strength sessions.

wger (https://wger.de, AGPL, self-hostable) is the open-source tracker this
project already accepts exports from, and it is the one that documents its API.
The endpoints we need are ``weightentry`` (weights), ``nutritiondiary`` (diary
items with ingredients) and ``workoutsession`` + ``workoutlog`` (training).

This is a manual import path, not an integration. It runs only when the athlete
asks for it, reads with ``GET`` only, and writes ordinary export files into
``data/nutrition/wger.json`` and ``data/workout/wger.json``; the file connectors
then do the storing. That keeps imports idempotent (ADR-0004) and leaves the
running app with no new outbound request (ADR-0005).

Usage:
    WGER_TOKEN=... .venv/bin/python -m app.connectors.wger_api [--dry-run]

The token is a personal API key (wger -> User settings -> API key), read from
the ``WGER_TOKEN`` environment variable, sent as ``Authorization: Token <key>``
and never logged or written to disk.

API notes, verified against https://wger.de/api/v2/schema:
- lists paginate as ``{count, next, previous, results}``;
- ``ingredient.energy`` is kcal per 100 g and its macros are g per 100 g
  (``help_text='In kcal per 100g'`` in wger/nutrition/models/ingredient.py), so
  a diary row contributes ``value * grams / 100``;
- a diary row is ``amount`` units of ``weight_unit`` (grams when that is null),
  and the gram value of a unit hangs off the ingredient as ``weight_units``;
- ``workoutlog`` is one row per set, which is what makes a session summary
  ("Squat 3x5 @ 100 kg") possible.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

from ..config import (
    DATA_DIR,
    DATA_NUTRITION_DIR,
    DATA_WORKOUT_DIR,
    ENV_FILE,
    WGER_BASE_URL,
    WGER_BASE_URL_ENV,
    WGER_INGREDIENT_BATCH,
    WGER_PAGE_LIMIT,
    WGER_TIMEOUT_S,
    WGER_TOKEN_ENV,
)

USER_AGENT = "coach-running/1.0"
# Exchange a long-lived JWT refresh token for a short-lived access token. This is
# wger's allauth headless surface, not simplejwt's /api/v2/token/refresh: the key
# minted on the API key page carries allauth claims (``token_use``, ``sid``), and
# simplejwt answers it with "Token has no type".
WGER_REFRESH_PATH = "/allauth/app/v1/tokens/refresh"
# One export per domain, stable on purpose: the connector keys an import on the
# file path, so a second pull replaces the rows the first one produced instead
# of appending a copy.
NUTRITION_EXPORT = "wger.json"
WORKOUT_EXPORT = "wger.json"
# wger ingredient field -> our macro key, both per 100 g except energy (kcal).
MACRO_FIELDS = (
    ("calories", "energy"),
    ("protein_g", "protein"),
    ("carbs_g", "carbohydrates"),
    ("fat_g", "fat"),
)

Transport = Callable[[urllib.request.Request, float], bytes]


class WgerError(RuntimeError):
    """A wger request failed in a way the athlete has to act on."""


def token_from_env() -> Optional[str]:
    """The personal API token, or ``None`` when the athlete has not set one."""
    return os.environ.get(WGER_TOKEN_ENV, "").strip() or None


def base_url_from_env() -> str:
    """The instance to pull from; a self-hoster can point it at their server."""
    return os.environ.get(WGER_BASE_URL_ENV, "").strip().rstrip("/") or WGER_BASE_URL


def is_jwt(token: str) -> bool:
    """True for a JWT (the refresh token wger's API key page also offers).

    A permanent token is an opaque string; a JWT is three base64url segments
    and always opens with the ``{"alg"`` header, i.e. ``eyJ``.
    """
    return token.count(".") == 2 and token.startswith("eyJ")


def _token_pair(payload: dict) -> tuple[Optional[str], Optional[str]]:
    """Read (access, refresh) out of allauth's ``{status, data, meta}`` reply.

    allauth puts the token pair in ``data`` for a refresh and in ``meta`` for a
    login, so both are accepted rather than pinning one shape.
    """
    buckets = [
        bucket
        for bucket in (payload.get("data"), payload.get("meta"), payload)
        if isinstance(bucket, dict)
    ]
    access = refresh = None
    for bucket in buckets:
        access = access or bucket.get("access_token") or bucket.get("access")
        refresh = refresh or bucket.get("refresh_token") or bucket.get("refresh")
    return access, refresh


def store_token(token: str, env_file: Path = ENV_FILE) -> None:
    """Write a rotated refresh token back to .env, keeping the other lines.

    wger sets ``ROTATE_REFRESH_TOKENS`` and ``BLACKLIST_AFTER_ROTATION``, so the
    refresh token that was just exchanged is dead. Persisting the new one is
    what lets the next pull work. The file is created 0600 and replaced
    atomically: a half-written .env would take every other key with it.
    """
    prefix = f"{WGER_TOKEN_ENV}="
    lines: list[str] = []
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith(prefix):
            lines[index] = f"{WGER_TOKEN_ENV}={token}"
            break
    else:
        lines.append(f"{WGER_TOKEN_ENV}={token}")
    env_file.parent.mkdir(parents=True, exist_ok=True)
    temp = env_file.with_name(env_file.name + ".tmp")
    temp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, env_file)


@dataclass(frozen=True)
class PullResult:
    """One pull: the two export payloads plus a count summary for the CLI."""

    nutrition: dict
    workout: dict
    stats: dict


def _urlopen(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _http_message(status: int) -> str:
    """Turn an HTTP status into advice, without echoing anything secret."""
    if status in (401, 403):
        return (
            "wger refused the token. Mint a personal API key (wger -> User "
            f"settings -> API key) and put it in {WGER_TOKEN_ENV}."
        )
    if status == 429:
        return "wger rate-limited this account. Wait a minute and run it again."
    return f"wger answered HTTP {status}."


class WgerClient:
    """Read-only client for the wger REST API.

    Only ``GET`` is implemented, plus the token exchange wger requires: data
    flows wger -> this app, never back. A permanent key goes out as
    ``Authorization: Token <key>``; a JWT refresh token is exchanged for a
    five-minute access token sent as ``Authorization: Bearer <token>``.
    """

    def __init__(
        self,
        token: str,
        base_url: str = WGER_BASE_URL,
        timeout: float = WGER_TIMEOUT_S,
        transport: Optional[Transport] = None,
        on_refresh: Optional[Callable[[str], None]] = None,
    ) -> None:
        if not token:
            raise WgerError(
                "No wger API token. Mint one under User settings -> API key on "
                f"the wger instance and put it in {WGER_TOKEN_ENV}."
            )
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._access: Optional[str] = None
        self._timeout = timeout
        self._transport = transport or _urlopen
        self._on_refresh = on_refresh

    def _auth(self) -> tuple[str, str]:
        """Authorization scheme and credential for the next request."""
        if not is_jwt(self._token):
            return "Token", self._token
        if self._access is None:
            self._exchange()
        return "Bearer", self._access or ""

    def _exchange(self) -> None:
        """Turn the stored refresh token into an access token.

        The rotated refresh token is handed to ``on_refresh`` because wger's
        strategy invalidates the one just used; without persisting it, the next
        pull would fail on a dead key. wger parses JSON only, so the body is a
        JSON object with allauth's ``refresh_token`` field.
        """
        request = urllib.request.Request(
            f"{self.base_url}{WGER_REFRESH_PATH}",
            data=json.dumps({"refresh_token": self._token}).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            body = self._transport(request, self._timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 401, 403):
                raise WgerError(
                    "wger rejected the refresh token: it was already exchanged "
                    "elsewhere or has expired. Mint a new key under User "
                    f"settings -> API key and update {WGER_TOKEN_ENV}."
                ) from exc
            raise WgerError(_http_message(exc.code)) from exc
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise WgerError(
                f"Could not reach wger at {self.base_url}: {reason}"
            ) from exc
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise WgerError(
                "wger did not answer the token exchange with JSON."
            ) from exc

        access, rotated = _token_pair(payload)
        if not access:
            raise WgerError(
                "wger accepted the key but returned no access token; mint a new "
                f"one under User settings -> API key and update {WGER_TOKEN_ENV}."
            )
        self._access = access
        if rotated and rotated != self._token:
            self._token = rotated
            if self._on_refresh is not None:
                self._on_refresh(rotated)

    def _url(self, path: str, params: dict) -> str:
        query = urllib.parse.urlencode(
            {key: value for key, value in params.items() if value is not None}
        )
        base = (
            path
            if path.startswith(("http://", "https://"))
            else f"{self.base_url}{path}"
        )
        return f"{base}?{query}" if query else base

    def _send(self, url: str, scheme: str, credential: str) -> dict:
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"{scheme} {credential}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            body = self._transport(request, self._timeout)
        except urllib.error.HTTPError:
            raise  # the caller decides whether an expired token is retryable
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise WgerError(
                f"Could not reach wger at {self.base_url}: {reason}"
            ) from exc
        try:
            return json.loads(body)
        except ValueError as exc:
            raise WgerError(
                f"wger answered with something that is not JSON: {url}"
            ) from exc

    def _request(self, url: str) -> dict:
        for attempt in (0, 1):
            scheme, credential = self._auth()
            try:
                return self._send(url, scheme, credential)
            except urllib.error.HTTPError as exc:
                # A five-minute access token can expire in the middle of a long
                # pull: refresh once, then stop retrying.
                if exc.code not in (401, 403) or not is_jwt(self._token) or attempt:
                    raise WgerError(_http_message(exc.code)) from exc
                self._access = None
        raise WgerError(_http_message(403))  # pragma: no cover - loop is bounded

    def get(self, path: str, **params) -> dict:
        """Read one object, e.g. a routine structure."""
        return self._request(self._url(path, params))

    def list(self, path: str, **params) -> list[dict]:
        """Read every page of a list endpoint."""
        url = self._url(path, {**params, "limit": WGER_PAGE_LIMIT})
        rows: list[dict] = []
        while url:
            page = self._request(url)
            rows.extend(page.get("results") or [])
            url = page.get("next") or ""
        return rows


def _num(value) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso_day(value) -> Optional[str]:
    """Date part of a wger timestamp; they are ISO 8601 with an offset."""
    text = str(value or "")
    return text[:10] if len(text) >= 10 and text[4] == "-" else None


def _parse_dt(value) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def weight_rows(entries: Iterable[dict]) -> list[dict]:
    """Map wger weight entries to ``{date, weight_kg}`` rows."""
    rows = []
    for entry in entries:
        day = _iso_day(entry.get("date"))
        kilograms = _num(entry.get("weight"))
        if day and kilograms:
            rows.append({"date": day, "weight_kg": round(kilograms, 1)})
    return sorted(rows, key=lambda row: row["date"])


def _unit_grams(ingredients: dict[int, dict]) -> dict[int, float]:
    """Map a weight-unit id to grams, read from the ingredients that use it."""
    grams: dict[int, float] = {}
    for ingredient in ingredients.values():
        for unit in ingredient.get("weight_units") or []:
            value = _num(unit.get("gram"))
            if unit.get("id") is not None and value:
                grams[unit["id"]] = value
    return grams


def _grams(item: dict, unit_grams: dict[int, float]) -> Optional[float]:
    """Mass of one diary item in grams; ``None`` when its unit is unknown."""
    amount = _num(item.get("amount"))
    if amount is None:
        return None
    unit = item.get("weight_unit")
    if unit in (None, ""):
        return amount
    grams_per_unit = unit_grams.get(unit)
    return None if grams_per_unit is None else amount * grams_per_unit


def nutrition_rows(
    items: Iterable[dict],
    ingredients: dict[int, dict],
    unit_grams: dict[int, float],
) -> tuple[list[dict], int]:
    """Aggregate diary items into one macro row per day.

    Returns the rows and how many items were skipped. Skip rather than guess:
    wger lets a plan outlive the ingredient a log refers to, and an item with an
    unknown weight unit has no mass we can trust.
    """
    by_day: dict[str, dict[str, float]] = {}
    skipped = 0
    for item in items:
        day = _iso_day(item.get("datetime"))
        ingredient = ingredients.get(item.get("ingredient"))
        grams = _grams(item, unit_grams)
        if not day or ingredient is None or not grams:
            skipped += 1
            continue
        bucket = by_day.setdefault(day, {})
        for key, field in MACRO_FIELDS:
            per_100g = _num(ingredient.get(field))
            if per_100g is None:
                continue
            bucket[key] = bucket.get(key, 0.0) + per_100g * grams / 100.0

    rows = []
    for day in sorted(by_day):
        macros = {}
        for key, _ in MACRO_FIELDS:
            if key in by_day[day]:
                value = by_day[day][key]
                macros[key] = round(value) if key == "calories" else round(value, 1)
        if macros:
            rows.append({"date": day, "macros": macros})
    return rows, skipped


def nutrition_payload(macros_rows: Iterable[dict], weights: Iterable[dict]) -> dict:
    """Merge macros and weights into the generic nutrition export shape.

    The generic reader expects one record per day carrying an optional ``macros``
    object and ``weight_kg``, so a weight-only day and a diary-only day both
    survive the round trip.
    """
    by_day: dict[str, dict] = {}
    for row in macros_rows:
        by_day.setdefault(row["date"], {"date": row["date"]})["macros"] = row["macros"]
    for row in weights:
        by_day.setdefault(row["date"], {"date": row["date"]})["weight_kg"] = row[
            "weight_kg"
        ]
    return {"nutrition": [by_day[day] for day in sorted(by_day)]}


def _duration_min(session: dict) -> Optional[int]:
    start = _parse_dt(session.get("datetime_start"))
    end = _parse_dt(session.get("datetime_end"))
    if start is None or end is None:
        return None
    # wger stores both ends with the same offset; guard against a naive/aware
    # mix rather than crash on a subtraction.
    if (start.tzinfo is None) != (end.tzinfo is None):
        end = end.replace(tzinfo=start.tzinfo)
    if end < start:
        return None
    return int(round((end - start).total_seconds() / 60))


def _exercises(logs: Iterable[dict], names: dict[int, str]) -> list[dict]:
    """Summarise sets into one entry per exercise: set count, top reps and load."""
    merged: dict[str, dict] = {}
    for log in logs:
        name = names.get(log.get("exercise"))
        if not name:
            continue
        entry = merged.setdefault(
            name, {"name": name, "sets": 0, "reps": None, "weight_kg": None}
        )
        entry["sets"] += 1
        reps = _num(log.get("repetitions"))
        if reps is not None and (entry["reps"] is None or reps > entry["reps"]):
            entry["reps"] = int(round(reps))
        weight = _num(log.get("weight"))
        if weight is not None and (
            entry["weight_kg"] is None or weight > entry["weight_kg"]
        ):
            entry["weight_kg"] = _number(weight)
    return list(merged.values())


def _number(value: float) -> float | int:
    """Drop the decimal point on whole kilograms: the notes read better."""
    rounded = round(value, 1)
    return int(rounded) if float(rounded).is_integer() else rounded


def workout_payload(
    sessions: Iterable[dict],
    logs: Iterable[dict],
    exercise_names: dict[int, str],
    day_names: dict[int, str],
) -> dict:
    """Map sessions and their set logs to the ``{"workouts": [...]}`` export."""
    by_session: dict = {}
    for log in logs:
        by_session.setdefault(log.get("session"), []).append(log)

    workouts = []
    for session in sessions:
        day = _iso_day(session.get("datetime_start"))
        if not day:
            continue
        title = day_names.get(session.get("day")) or "wger session"
        workouts.append(
            {
                "name": title,
                "sessions": [
                    {
                        "date": day,
                        "kind": "strength",
                        "title": title,
                        "duration_min": _duration_min(session),
                        "notes": (session.get("notes") or "").strip(),
                        "status": "completed",
                        "exercises": _exercises(
                            by_session.get(session.get("id"), []), exercise_names
                        ),
                    }
                ],
            }
        )
    return {"workouts": workouts}


def _batches(values: list[int]) -> Iterable[str]:
    for start in range(0, len(values), WGER_INGREDIENT_BATCH):
        yield ",".join(
            str(value) for value in values[start : start + WGER_INGREDIENT_BATCH]
        )


def _fetch_ingredients(client: WgerClient, items: Iterable[dict]) -> dict[int, dict]:
    ids = sorted({item.get("ingredient") for item in items if item.get("ingredient")})
    found: dict[int, dict] = {}
    for batch in _batches(ids):
        for row in client.list("/api/v2/ingredient/", id__in=batch):
            found[row["id"]] = row
    return found


def _translated_name(exercise: dict) -> str:
    """English name when wger has one, otherwise the first translation."""
    translations = [
        translation
        for translation in exercise.get("translations") or []
        if (translation.get("name") or "").strip()
    ]
    for translation in translations:
        if translation.get("language") == 2:
            return translation["name"].strip()
    return translations[0]["name"].strip() if translations else ""


def _fetch_exercise_names(client: WgerClient, logs: Iterable[dict]) -> dict[int, str]:
    ids = sorted({log.get("exercise") for log in logs if log.get("exercise")})
    names: dict[int, str] = {}
    for batch in _batches(ids):
        for row in client.list("/api/v2/exerciseinfo/", id__in=batch):
            name = _translated_name(row)
            if name:
                names[row["id"]] = name
    return names


def _fetch_day_names(client: WgerClient, routine_ids: Iterable[int]) -> dict[int, str]:
    """Day id -> name, so a session is titled "Push A" rather than "Session"."""
    names: dict[int, str] = {}
    for routine_id in sorted(routine_ids):
        structure = client.get(f"/api/v2/routine/{routine_id}/structure/")
        for day in structure.get("days") or []:
            if day.get("id") is not None and (day.get("name") or "").strip():
                names[day["id"]] = day["name"].strip()
    return names


def pull(client: WgerClient) -> PullResult:
    """Read weight, nutrition and workouts from wger. ``GET`` requests only."""
    weights = weight_rows(client.list("/api/v2/weightentry/", ordering="date"))

    items = client.list("/api/v2/nutritiondiary/", ordering="datetime")
    ingredients = _fetch_ingredients(client, items)
    nutrition, skipped = nutrition_rows(items, ingredients, _unit_grams(ingredients))

    sessions = client.list("/api/v2/workoutsession/", ordering="datetime_start")
    logs = client.list("/api/v2/workoutlog/") if sessions else []
    day_names = _fetch_day_names(
        client,
        {session.get("routine") for session in sessions if session.get("routine")},
    )
    workout = workout_payload(
        sessions, logs, _fetch_exercise_names(client, logs), day_names
    )

    return PullResult(
        nutrition=nutrition_payload(nutrition, weights),
        workout=workout,
        stats={
            "weights": len(weights),
            "nutrition": len(nutrition),
            "diary_items_skipped": skipped,
            "sessions": sum(len(w["sessions"]) for w in workout["workouts"]),
        },
    )


def write_exports(
    result: PullResult,
    nutrition_dir: Path = DATA_NUTRITION_DIR,
    workout_dir: Path = DATA_WORKOUT_DIR,
) -> list[Path]:
    """Write both exports atomically so the connector never sees half a file."""
    written = []
    targets = (
        (nutrition_dir, NUTRITION_EXPORT, result.nutrition),
        (workout_dir, WORKOUT_EXPORT, result.workout),
    )
    for directory, name, payload in targets:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / name
        temp = target.with_name(target.name + ".tmp")
        temp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, target)
        written.append(target)
    return written


def main(argv: Optional[list[str]] = None) -> int:
    """Pull wger over the REST API and write the export files."""
    parser = argparse.ArgumentParser(
        prog="python -m app.connectors.wger_api",
        description=(
            "Pull weight, nutrition and strength sessions from wger and write "
            "export files the app imports. Reads only: nothing is sent to wger."
        ),
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=f"wger instance (default: ${WGER_BASE_URL_ENV} or {WGER_BASE_URL})",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=DATA_DIR, help="where data/ lives"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be imported, write nothing",
    )
    args = parser.parse_args(argv)
    base_url = args.base_url or base_url_from_env()

    token = token_from_env()
    if token is None:
        print(
            f"wger: no token. Mint one at {base_url} (User settings -> API "
            f"key) and put it in {WGER_TOKEN_ENV}.",
            file=sys.stderr,
        )
        return 2

    rotated: list[bool] = []

    def keep_rotated(new_token: str) -> None:
        # wger blacklists the exchanged refresh token, so the new one has to
        # land in .env or the next pull dies on a dead key.
        store_token(new_token)
        rotated.append(True)

    try:
        result = pull(WgerClient(token, base_url=base_url, on_refresh=keep_rotated))
    except WgerError as exc:
        print(f"wger: {exc}", file=sys.stderr)
        return 1

    if rotated:
        print(f"Rotated {WGER_TOKEN_ENV} in .env (wger invalidates the old one).")

    stats = result.stats
    summary = (
        f"wger: {stats['weights']} weight entries, {stats['nutrition']} nutrition "
        f"days, {stats['sessions']} strength sessions"
    )
    if stats["diary_items_skipped"]:
        summary += f" ({stats['diary_items_skipped']} diary items skipped)"
    print(summary)

    if args.dry_run:
        return 0

    written = write_exports(
        result, args.data_dir / "nutrition", args.data_dir / "workout"
    )
    print("Wrote " + " and ".join(str(path) for path in written) + ".")
    print("Press the reload button in the app to import them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
