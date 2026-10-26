# wger over its REST API

[wger](https://wger.de) is a free, open-source workout and nutrition tracker
(AGPL, self-hostable). Besides the JSON export the app already reads from
`data/workout/`, the app can pull an account directly: weight, nutrition and
strength sessions, once, when you ask for it.

Nothing is fetched in the background. The pull happens on a button press (or one
command), reads only, and leaves the data in `data/` as a normal export that the
usual connectors import.

## Get an API key

1. Sign in on your wger instance.
2. Open **User settings → API key**. Two kinds of key are offered: a
   **permanent token** and a **long-lived JWT refresh token**. Both work here.
3. Put it in `.env` at the project root (gitignored, never committed):

```ini
WGER_TOKEN=your-personal-api-key
```

A self-hosted instance also needs its address:

```ini
WGER_BASE_URL=https://wger.example.org
```

The key is read by the server and sent as `Authorization: Token <key>` (permanent
token) or exchanged at `/allauth/app/v1/tokens/refresh` for a short-lived access
token sent as `Authorization: Bearer <token>` (JWT). It is never written to
`coach.db`, never logged, and never sent to the browser — the Import view only
learns whether a key exists.

### About the JWT refresh token

wger's headless strategy rotates a refresh token every time it is exchanged, so
the value in `.env` **dies on the first pull**. The app therefore writes the
replacement back into `.env` on every pull (same line, file mode 600, other keys
untouched, atomic replace). Three consequences: keep `.env` writable, do not
copy the old value to another machine, and do not pull from two places at once
(the button and the CLI) — each exchange replaces the token the other would use.

A permanent token does not rotate and never rewrites the file, which makes it
the quieter choice if you switch machines or copy `.env` around.

## Pull

- **In the app**: **Import → wger over its REST API → Connect to wger**. The
  status line reports how many weights, nutrition days and sessions arrived.
- **From a terminal**: `WGER_TOKEN=… .venv/bin/python -m app.connectors.wger_api`.
  Add `--dry-run` to see the counts without writing anything, `--base-url` to
  target another instance, and `--data-dir` to write somewhere else.

The pull writes `data/nutrition/wger.json` and `data/workout/wger.json`. Pressing
the button twice replaces the rows the previous pull produced; it never
duplicates them.

## What is imported

| Domain | wger endpoint | Becomes |
| --- | --- | --- |
| Weight | `/api/v2/weightentry/` | one weight per day, in the Profile and Fuel views |
| Nutrition | `/api/v2/nutritiondiary/` + `/api/v2/ingredient/` | daily kcal, protein, carbs and fat |
| Training | `/api/v2/workoutsession/`, `/api/v2/workoutlog/`, `/api/v2/routine/{id}/structure/`, `/api/v2/exerciseinfo/` | one strength session per logged workout, with sets, reps and top load per exercise |

Macros are recomputed locally from wger's per-100 g ingredient values, the
logged amount and the weight unit. A diary item whose ingredient was deleted from
the database has no trustworthy mass, so it is skipped and counted in the status
line instead of being guessed.

## What is not imported

- **Running activities.** wger stores no GPS tracks. Run files still come from
  OpenTracks, Strava or Garmin into `data/running/`.
- **Planned routines.** Only logged workouts become sessions. A routine you have
  not trained is a plan, and plans in this app come from the Planner.
- **Notes on individual sets, RIR, rest times.** The export carries the session
  note and one summary per exercise; the details stay in wger.

## Failures you may see

| Message | Meaning |
| --- | --- |
| `No wger API token…` | `.env` has no `WGER_TOKEN`; add it and restart the app (the env is read at start-up). |
| `wger refused the token…` | A permanent key is wrong or revoked. Mint a new one under User settings → API key. |
| `wger rejected the refresh token…` | The JWT was already exchanged elsewhere (another machine, an older copy of `.env`) or has expired. Mint a new key. |
| `Could not reach wger at …` | No network, or a self-hosted `WGER_BASE_URL` that is down. |
| `wger rate-limited this account…` | Too many calls in a minute; wait and pull again. |

The API is versioned (`/api/v2/`) and its schema is published at
`/api/v2/schema`, so a breaking change surfaces as an error message rather than
silently partial data. The decision to add this outbound path is recorded in
[ADR-0009](adr/0009-opt-in-wger-pull.md).
