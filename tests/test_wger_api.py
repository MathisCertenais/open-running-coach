"""Tests for the opt-in wger REST pull (app/connectors/wger_api.py).

No socket is opened: a fake transport stands in for wger, so these tests pin the
request shape, the pagination walk, the per-100 g macro maths and the fact that
the pull writes files the ordinary file connectors already understand.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse

import pytest

from app.connectors import (
    import_nutrition_dir,
    import_wger,
    import_workout_dir,
    wger_api,
)
from app.store import Store

TOKEN = "wger-secret-token"
# Captured before any test monkeypatches the attribute on the module.
_CLIENT = wger_api.WgerClient

INGREDIENTS = [
    {
        "id": 10,
        "energy": 100,
        "protein": "10.0",
        "carbohydrates": "20.0",
        "fat": "4.0",
        "weight_units": [{"id": 7, "gram": 30, "name": "slice"}],
    },
    {
        "id": 11,
        "energy": 50,
        "protein": "5.0",
        "carbohydrates": "0.0",
        "fat": "2.0",
        "weight_units": [],
    },
]

DIARY = [
    {
        "id": "a",
        "datetime": "2026-10-20T08:00:00+02:00",
        "ingredient": 10,
        "amount": "150.00",
        "weight_unit": None,
    },
    {
        "id": "b",
        "datetime": "2026-10-20T12:30:00+02:00",
        "ingredient": 11,
        "amount": "2.00",
        "weight_unit": 7,
    },
    {
        "id": "c",
        "datetime": "2026-10-21T09:00:00+02:00",
        "ingredient": 99,  # deleted ingredient: must be skipped, not guessed
        "amount": "100.00",
        "weight_unit": None,
    },
]

WEIGHTS = [
    {"id": "w1", "date": "2026-10-20", "weight": "72.54"},
    {"id": "w2", "date": "2026-10-22", "weight": "72.10"},
]

SESSIONS = [
    {
        "id": 1,
        "routine": 5,
        "day": 9,
        "notes": "felt strong",
        "impression": "2",
        "datetime_start": "2026-10-20T18:00:00+02:00",
        "datetime_end": "2026-10-20T18:45:00+02:00",
    }
]

LOGS = [
    {"session": 1, "exercise": 100, "repetitions": "5.00", "weight": "100.00"},
    {"session": 1, "exercise": 100, "repetitions": "5.00", "weight": "105.00"},
    {"session": 1, "exercise": 100, "repetitions": "5.00", "weight": "105.00"},
    {"session": 1, "exercise": 101, "repetitions": "10.00", "weight": None},
]

EXERCISES = [
    {"id": 100, "translations": [{"language": 2, "name": "Squat"}]},
    {"id": 101, "translations": [{"language": 1, "name": "Planche"}]},
]

ROUTES = {
    "/api/v2/weightentry/": WEIGHTS,
    "/api/v2/nutritiondiary/": DIARY,
    "/api/v2/ingredient/": INGREDIENTS,
    "/api/v2/workoutsession/": SESSIONS,
    "/api/v2/workoutlog/": LOGS,
    "/api/v2/exerciseinfo/": EXERCISES,
    "/api/v2/routine/5/structure/": {"days": [{"id": 9, "name": "Leg day"}]},
}


class FakeWger:
    """A wger stand-in that serves paginated lists from a dict of routes."""

    def __init__(self, routes=ROUTES, page_size=2, errors=None):
        self.routes = routes
        self.page_size = page_size
        self.errors = errors or {}
        self.calls: list[dict] = []

    def __call__(self, request, timeout):
        parsed = urllib.parse.urlparse(request.full_url)
        params = urllib.parse.parse_qs(parsed.query)
        self.calls.append(
            {
                "path": parsed.path,
                "params": {key: value[0] for key, value in params.items()},
                "auth": request.get_header("Authorization"),
            }
        )
        status = self.errors.get(parsed.path)
        if status:
            raise urllib.error.HTTPError(request.full_url, status, "error", {}, None)
        route = self.routes.get(parsed.path)
        if route is None:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
        if isinstance(route, dict):
            return json.dumps(route).encode("utf-8")

        offset = int(params.get("offset", ["0"])[0])
        limit = min(int(params.get("limit", ["20"])[0]), self.page_size)
        page = route[offset : offset + limit]
        next_url = None
        if offset + limit < len(route):
            query = {key: value[0] for key, value in params.items() if key != "offset"}
            query["offset"] = str(offset + limit)
            next_url = (
                "https://wger.test" + parsed.path + "?" + urllib.parse.urlencode(query)
            )
        body = {
            "count": len(route),
            "next": next_url,
            "previous": None,
            "results": page,
        }
        return json.dumps(body).encode("utf-8")


def client(fake=None, token=TOKEN):
    return _CLIENT(token, transport=fake or FakeWger())


def fake_client(fake):
    """A WgerClient factory for `main()`, bypassing the monkeypatched class."""
    return lambda token, base_url, **kwargs: _CLIENT(token, transport=fake)


# ---------------------------------------------------------------------------
# Transport: auth, pagination, failures
# ---------------------------------------------------------------------------
def test_the_token_is_sent_on_every_request():
    fake = FakeWger()
    client(fake).list("/api/v2/weightentry/")

    assert fake.calls
    assert {call["auth"] for call in fake.calls} == {f"Token {TOKEN}"}


def test_a_multi_page_list_is_walked_to_the_end():
    fake = FakeWger(page_size=1)
    rows = client(fake).list("/api/v2/weightentry/")

    assert len(rows) == len(WEIGHTS)
    assert len(fake.calls) == 2  # one row per page, then `next: null`


def test_a_missing_token_says_where_to_get_one():
    with pytest.raises(wger_api.WgerError) as excinfo:
        wger_api.WgerClient("")

    assert wger_api.WGER_TOKEN_ENV in str(excinfo.value)
    assert "API key" in str(excinfo.value)


def test_a_refused_token_explains_the_fix_without_echoing_it():
    fake = FakeWger(errors={"/api/v2/weightentry/": 403})

    with pytest.raises(wger_api.WgerError) as excinfo:
        client(fake).list("/api/v2/weightentry/")

    message = str(excinfo.value)
    assert "API key" in message
    assert TOKEN not in message


def test_a_network_failure_names_the_instance(monkeypatch):
    def boom(request, timeout):
        raise urllib.error.URLError("connection refused")

    with pytest.raises(wger_api.WgerError) as excinfo:
        client(boom).list("/api/v2/weightentry/")

    assert "Could not reach wger" in str(excinfo.value)
    assert "https://wger.de" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------
def test_weight_entries_become_dated_kilograms():
    rows = wger_api.weight_rows(WEIGHTS + [{"date": "", "weight": "70"}])

    assert rows == [
        {"date": "2026-10-20", "weight_kg": 72.5},
        {"date": "2026-10-22", "weight_kg": 72.1},
    ]


def test_diary_items_become_one_row_of_macros_per_day():
    ingredients = {row["id"]: row for row in INGREDIENTS}

    rows, skipped = wger_api.nutrition_rows(DIARY, ingredients, {7: 30.0})

    assert skipped == 1
    assert rows == [
        {
            "date": "2026-10-20",
            "macros": {
                "calories": 180,
                "protein_g": 18.0,
                "carbs_g": 30.0,
                "fat_g": 7.2,
            },
        }
    ]


def test_a_weight_unit_is_converted_with_its_gram_value():
    ingredient = {"energy": 100, "protein": "1", "carbohydrates": "1", "fat": "1"}
    item = {
        "datetime": "2026-10-20T10:00:00Z",
        "ingredient": 1,
        "amount": "2",
        "weight_unit": 7,
    }

    rows, _ = wger_api.nutrition_rows([item], {1: ingredient}, {7: 30.0})

    # 2 slices x 30 g = 60 g, so 100 kcal/100 g -> 60 kcal.
    assert rows[0]["macros"]["calories"] == 60


def test_an_unknown_weight_unit_is_skipped_not_guessed():
    ingredient = {"energy": 100, "protein": "1", "carbohydrates": "1", "fat": "1"}
    item = {
        "datetime": "2026-10-20T10:00:00Z",
        "ingredient": 1,
        "amount": "2",
        "weight_unit": 404,
    }

    rows, skipped = wger_api.nutrition_rows([item], {1: ingredient}, {})

    assert rows == []
    assert skipped == 1


def test_sessions_carry_duration_title_and_a_set_summary():
    payload = wger_api.workout_payload(
        SESSIONS, LOGS, {100: "Squat", 101: "Plank"}, {9: "Leg day"}
    )

    workout = payload["workouts"][0]
    session = workout["sessions"][0]
    assert workout["name"] == "Leg day"
    assert session["date"] == "2026-10-20"
    assert session["duration_min"] == 45
    assert session["notes"] == "felt strong"
    assert session["exercises"] == [
        {"name": "Squat", "sets": 3, "reps": 5, "weight_kg": 105},
        {"name": "Plank", "sets": 1, "reps": 10, "weight_kg": None},
    ]


def test_an_exercise_without_a_name_is_left_out():
    payload = wger_api.workout_payload(SESSIONS, LOGS, {100: "Squat"}, {})

    exercises = payload["workouts"][0]["sessions"][0]["exercises"]

    assert [exercise["name"] for exercise in exercises] == ["Squat"]


def test_a_session_without_a_start_time_is_dropped():
    broken = [{**SESSIONS[0], "datetime_start": None}]

    assert wger_api.workout_payload(broken, [], {}, {})["workouts"] == []


# ---------------------------------------------------------------------------
# The full pull, and the files it writes
# ---------------------------------------------------------------------------
def test_a_pull_reads_weight_nutrition_and_sessions():
    result = wger_api.pull(client(FakeWger()))

    assert result.stats == {
        "weights": 2,
        "nutrition": 1,
        "diary_items_skipped": 1,
        "sessions": 1,
    }
    assert result.nutrition["nutrition"] == [
        {
            "date": "2026-10-20",
            "macros": {
                "calories": 180,
                "protein_g": 18.0,
                "carbs_g": 30.0,
                "fat_g": 7.2,
            },
            "weight_kg": 72.5,
        },
        {"date": "2026-10-22", "weight_kg": 72.1},
    ]
    assert result.workout["workouts"][0]["name"] == "Leg day"
    exercises = result.workout["workouts"][0]["sessions"][0]["exercises"]
    # English is preferred; a French-only exercise keeps its translation.
    assert [exercise["name"] for exercise in exercises] == ["Squat", "Planche"]


def test_the_pull_never_writes_back_to_wger():
    fake = FakeWger()
    wger_api.pull(client(fake))

    # The fake is only ever called through GET; the client has no other verb.
    assert all(call["path"].startswith("/api/v2/") for call in fake.calls)
    assert not hasattr(wger_api.WgerClient, "post")


def test_the_export_files_land_in_the_connector_folders(tmp_path):
    result = wger_api.pull(client(FakeWger()))
    nutrition_dir = tmp_path / "nutrition"
    workout_dir = tmp_path / "workout"

    written = wger_api.write_exports(result, nutrition_dir, workout_dir)

    assert written == [nutrition_dir / "wger.json", workout_dir / "wger.json"]
    assert all(path.exists() for path in written)
    assert not (nutrition_dir / "wger.json.tmp").exists()


def test_the_written_exports_are_imported_by_the_file_connectors(tmp_path):
    """The end-to-end promise: a wger pull ends up as rows in SQLite."""
    store = Store(tmp_path / "test.db")
    nutrition_dir = tmp_path / "nutrition"
    workout_dir = tmp_path / "workout"
    result = wger_api.pull(client(FakeWger()))
    wger_api.write_exports(result, nutrition_dir, workout_dir)

    nutrition_stats = import_nutrition_dir(store, nutrition_dir)
    workout_stats = import_workout_dir(store, workout_dir)

    day = store.get_nutrition("2026-10-20")
    assert nutrition_stats["logs"] == 1
    assert day["macros"]["calories"] == 180
    assert {row["date"] for row in store.list_weights()} == {"2026-10-20", "2026-10-22"}
    session = store.list_sessions()[0]
    assert workout_stats["sessions"] == 1
    assert session["title"] == "Leg day"
    assert session["duration_min"] == 45
    assert session["notes"] == "felt strong"
    assert {(e["name"], e["sets"], e["reps"]) for e in session["exercises"]} == {
        ("Squat", 3, 5),
        # Exercise 101 has no English translation, so the first one is used.
        ("Planche", 1, 10),
    }


def test_a_second_pull_replaces_instead_of_duplicating(tmp_path):
    store = Store(tmp_path / "test.db")
    kwargs = {
        "nutrition_dir": tmp_path / "nutrition",
        "workout_dir": tmp_path / "workout",
        "transport": FakeWger(),
    }

    for _ in range(2):
        import_wger(store, TOKEN, base_url="https://wger.test", **kwargs)

    assert len(store.list_weights()) == 2
    assert len(store.list_sessions()) == 1


# ---------------------------------------------------------------------------
# The seam the API route uses
# ---------------------------------------------------------------------------
def test_import_wger_pulls_writes_and_imports(tmp_path):
    store = Store(tmp_path / "test.db")

    result = import_wger(
        store,
        TOKEN,
        base_url="https://wger.test",
        nutrition_dir=tmp_path / "nutrition",
        workout_dir=tmp_path / "workout",
        transport=FakeWger(),
    )

    assert result["pulled"] == {
        "weights": 2,
        "nutrition": 1,
        "diary_items_skipped": 1,
        "sessions": 1,
    }
    assert result["nutrition"] == {"files": 1, "logs": 1, "weights": 2}
    assert result["workout"] == {"files": 1, "sessions": 1}
    assert store.get_nutrition("2026-10-20")["macros"]["calories"] == 180
    assert store.list_sessions()[0]["title"] == "Leg day"


def test_an_api_error_propagates_to_the_caller(tmp_path):
    store = Store(tmp_path / "test.db")

    with pytest.raises(wger_api.WgerError):
        import_wger(
            store,
            TOKEN,
            nutrition_dir=tmp_path / "nutrition",
            workout_dir=tmp_path / "workout",
            transport=FakeWger(errors={"/api/v2/weightentry/": 403}),
        )

    assert list(tmp_path.glob("nutrition/*")) == []


# ---------------------------------------------------------------------------
# Configuration from the environment
# ---------------------------------------------------------------------------
def test_the_token_is_read_from_the_environment(monkeypatch):
    monkeypatch.delenv(wger_api.WGER_TOKEN_ENV, raising=False)
    assert wger_api.token_from_env() is None

    monkeypatch.setenv(wger_api.WGER_TOKEN_ENV, "  abc123  ")
    assert wger_api.token_from_env() == "abc123"


def test_a_self_hosted_instance_can_be_pointed_at(monkeypatch):
    monkeypatch.delenv(wger_api.WGER_BASE_URL_ENV, raising=False)
    assert wger_api.base_url_from_env() == wger_api.WGER_BASE_URL

    monkeypatch.setenv(wger_api.WGER_BASE_URL_ENV, "https://wger.example.org/")
    assert wger_api.base_url_from_env() == "https://wger.example.org"


# ---------------------------------------------------------------------------
# JWT refresh tokens (what wger's API key page also mints)
# ---------------------------------------------------------------------------
JWT = "eyJhbGciOiJSUzI1NiJ9.eyJ0b2tlbl90eXBlIjoicmVmcmVzaCJ9.c2lnbmF0dXJl"


def rotated_jwt(n: int) -> str:
    """A three-segment token, like the one wger hands back on rotation."""
    return "eyJhbGciOiJSUzI1NiJ9.eyJzZXEiOiB7bn19.c2lnbmF0dXJl"


class FakeJwtWger(FakeWger):
    """Serves lists and rotates a refresh token on every exchange."""

    def __init__(
        self,
        routes=ROUTES,
        page_size=2,
        errors=None,
        fail_first_get=False,
        envelope="data",
    ):
        super().__init__(routes, page_size, errors)
        self.exchanges = 0
        self.posts: list[dict] = []
        self.fail_first_get = fail_first_get
        self.envelope = envelope
        self.gets = 0

    def __call__(self, request, timeout):
        parsed = urllib.parse.urlparse(request.full_url)
        if parsed.path == wger_api.WGER_REFRESH_PATH:
            self.exchanges += 1
            self.posts.append(
                {
                    "auth": request.get_header("Authorization"),
                    "type": request.get_header("Content-type"),
                    "parsed_as": request.data[:1],
                    "body": json.loads(request.data.decode()),
                }
            )
            pair = {
                "access_token": f"access-{self.exchanges}",
                "refresh_token": rotated_jwt(self.exchanges),
            }
            payload = {
                "status": 200,
                "data": pair if self.envelope == "data" else {},
                "meta": {"is_authenticated": True},
            }
            if self.envelope == "meta":
                payload["meta"].update(pair)
            return json.dumps(payload).encode("utf-8")
        self.gets += 1
        if self.fail_first_get and self.gets == 1:
            raise urllib.error.HTTPError(request.full_url, 401, "expired", {}, None)
        return super().__call__(request, timeout)


def test_a_jwt_is_exchanged_for_a_bearer_access_token():
    fake = FakeJwtWger()
    wger_api.WgerClient(JWT, transport=fake).list("/api/v2/weightentry/")

    assert fake.exchanges == 1
    assert fake.posts[0]["auth"] is None  # the refresh token is the body
    assert fake.posts[0]["body"] == {"refresh_token": JWT}
    assert fake.calls[0]["auth"] == "Bearer access-1"


def test_the_rotated_refresh_token_is_handed_back_for_storage():
    stored: list[str] = []

    wger_api.WgerClient(JWT, transport=FakeJwtWger(), on_refresh=stored.append).list(
        "/api/v2/weightentry/"
    )

    assert stored == [rotated_jwt(1)]


def test_an_access_token_that_expired_mid_pull_is_refreshed_once():
    fake = FakeJwtWger(fail_first_get=True)

    rows = wger_api.WgerClient(JWT, transport=fake).list("/api/v2/weightentry/")

    assert len(rows) == len(WEIGHTS)
    assert fake.exchanges == 2
    assert fake.calls[-1]["auth"] == "Bearer access-2"


def test_a_burned_refresh_token_says_to_mint_a_new_key():
    fake = FakeWger(errors={wger_api.WGER_REFRESH_PATH: 401})

    with pytest.raises(wger_api.WgerError) as excinfo:
        wger_api.WgerClient(JWT, transport=fake).list("/api/v2/weightentry/")

    message = str(excinfo.value)
    assert "already exchanged" in message
    assert wger_api.WGER_TOKEN_ENV in message
    assert JWT not in message


def test_the_token_pair_is_also_read_from_allauth_meta():
    fake = FakeJwtWger(envelope="meta")

    wger_api.WgerClient(JWT, transport=fake).list("/api/v2/weightentry/")

    assert fake.calls[0]["auth"] == "Bearer access-1"


def test_a_permanent_token_is_sent_without_an_exchange():
    fake = FakeWger()
    wger_api.WgerClient(TOKEN, transport=fake).list("/api/v2/weightentry/")

    assert isinstance(fake, FakeWger)
    assert fake.calls[0]["auth"] == f"Token {TOKEN}"


def test_token_shapes_are_recognised():
    assert wger_api.is_jwt(JWT)
    assert not wger_api.is_jwt("0123456789abcdef" * 3)
    assert not wger_api.is_jwt("two.dots")


def test_a_rotated_token_replaces_only_its_own_line(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ALBERT_API_KEY=keep-me\nWGER_TOKEN=stale-token\nROOT_PASSWORD=also-keep\n",
        encoding="utf-8",
    )

    wger_api.store_token("fresh-token", env_file)

    lines = env_file.read_text(encoding="utf-8").splitlines()
    assert lines == [
        "ALBERT_API_KEY=keep-me",
        "WGER_TOKEN=fresh-token",
        "ROOT_PASSWORD=also-keep",
    ]
    assert env_file.stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / ".env.tmp").exists()


def test_a_rotated_token_is_appended_when_the_line_is_missing(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ALBERT_API_KEY=keep-me\n", encoding="utf-8")

    wger_api.store_token("fresh-token", env_file)

    assert env_file.read_text(encoding="utf-8").splitlines() == [
        "ALBERT_API_KEY=keep-me",
        "WGER_TOKEN=fresh-token",
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def test_the_cli_refuses_without_a_token(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv(wger_api.WGER_TOKEN_ENV, raising=False)

    code = wger_api.main(["--data-dir", str(tmp_path)])

    assert code == 2
    assert wger_api.WGER_TOKEN_ENV in capsys.readouterr().err
    assert not (tmp_path / "nutrition").exists()


def test_the_cli_dry_run_writes_nothing(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv(wger_api.WGER_TOKEN_ENV, TOKEN)
    monkeypatch.setattr(wger_api, "WgerClient", fake_client(FakeWger()))

    code = wger_api.main(["--data-dir", str(tmp_path), "--dry-run"])

    assert code == 0
    assert "2 weight entries" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_the_cli_writes_the_exports(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv(wger_api.WGER_TOKEN_ENV, TOKEN)
    monkeypatch.setattr(wger_api, "WgerClient", fake_client(FakeWger()))

    code = wger_api.main(["--data-dir", str(tmp_path)])

    assert code == 0
    assert (tmp_path / "nutrition" / "wger.json").exists()
    assert (tmp_path / "workout" / "wger.json").exists()
    printed = capsys.readouterr().out
    assert "reload button" in printed
    assert TOKEN not in printed


def test_the_cli_reports_a_wger_error(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv(wger_api.WGER_TOKEN_ENV, TOKEN)
    fake = FakeWger(errors={"/api/v2/weightentry/": 403})
    monkeypatch.setattr(wger_api, "WgerClient", fake_client(fake))

    code = wger_api.main(["--data-dir", str(tmp_path)])

    assert code == 1
    assert "API key" in capsys.readouterr().err
