# Coach Running 🏃

[![CI](https://github.com/MathisCertenais/open-running-coach/actions/workflows/ci.yml/badge.svg)](https://github.com/MathisCertenais/open-running-coach/actions/workflows/ci.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)

Local running-tracking dashboard, inspired by Strava. It reads your activity
files in **KMZ** (OpenTracks), **GPX** or **TCX** format (e.g. Strava exports),
computes your statistics, and displays the route on a map. Drop files into
`data/running/` (see **Data folders & external connectors** below).

## Features

**Tracking & map**
- 📋 List of all your runs (sorted by date, most recent first)
- 🗺️ Interactive map of the route (OpenStreetMap), colored by speed, with a
  speed legend
- 📊 Statistics: distance, moving time, average pace, elevation, max speed,
  heart rate (when present in the file)
- 📝 Personal notes per run (persisted in `coach.db`)
- ⬆️ **Drag and drop import**: drop KMZ/GPX/TCX activities, nutrition exports or
  workout files into the Import view. Each zone only accepts the formats its
  importer understands, and a file is parsed before it replaces anything.
- 🌙 **Dark theme**: follows the operating system, one click to override; the
  choice is remembered.
- 🔄 Automatic re-read of the `data/` folder (↻ button or reload)

**Advanced analysis (per run)**
- 🔢 **Splits**: pace per kilometer
- 🔁 **Laps**: analysis of the manual segments (your interval workouts)
- 🎨 **Pace zones**: time/distance spent in 6 zones (recovery → sprint)
- ⛰️ **GAP**: grade-adjusted pace (flat-ground equivalent)

**Global views**
- 🔥 **Personal heatmap**: all your routes overlaid
- 🏆 **Records**: best efforts (400 m, 1 km, 1 mile → marathon) + repeated routes
  (matched runs) to track your progression
- 📈 **Monthly statistics**: distance/time/elevation per month + comparison
- 🎯 **Goals**: weekly / monthly / yearly, in distance, time or elevation,
  with a progress bar

**Coaching (pace-based, no heart rate needed)**
- 📊 **Training load**: daily pace-based load (zone-weighted minutes), or
  session-RPE × duration when you log an effort (Foster scale)
- 🏋️ **Fitness / fatigue / form (CTL / ATL / TSB)**: Coggan Performance
  Management Chart with "fresh / neutral / fatigued" bands
- ⚠️ **Injury risk (ACWR)**: Acute:Chronic Workload Ratio (Gabbett 2016) with
  alert bands and trend
- 🎚️ **Intensity distribution (80/10/10)**: time in easy / moderate / hard
  vs the polarised ideal (Seiler 2010): 80% easy, 10% moderate, 10% hard
- 🫁 **VO2max & race predictor**: effective VO2max (Daniels VDOT) + race-time
  predictions (Riegel), with predicted-vs-actual comparison
- 🗓️ **Training plans**: periodized plan generator (race or weekly-volume
  goal), 80/20 distribution, +10% weekly progression, deload every 4th week,
  plus scheduled strength/mobility/rest support sessions
- 🩹 **Post-run check-in**: RPE, session intent, surface, completion, readiness,
  sleep, stress, legs, a structured pain log (location/side/severity/timing/
  trend) and a race flag — the injury-prevention loop
- 📅 **Training planner**: a weekly view merging runs from your files with
  strength, mobility, cross-training and rest sessions (planned/completed/
  skipped); support load is tracked separately from running load
- ⛽ **Fuel & recovery (optional)**: a daily check-in for hydration, energy,
  appetite, **steps**, fueling and supplements (adherence only), linked to your
  weight and training load. Coach insights flag rapid weight loss, low energy
  and **sedentary days** — never medical or dietary prescriptions.
- 🤖 **Assistant coach (optional)**: rule-based insight cards that always work
  offline, plus a conversational coach powered by a local Ollama model or any
  OpenAI-compatible endpoint. The LLM only receives compact derived metrics —
  never your GPS coordinates.

**Home & accessibility**
- 🏠 **Showcase home**: all KPIs and the AI coach side by side, then schedule,
  race history and stats — the most important features first.
- ♿ **Accessible**: WCAG 2.1/2.2 AA-oriented — skip link, landmarks, keyboard
  navigation, ARIA states, visible focus, reduced-motion support and
  contrast-safe colors (automated axe-core audit clean on every view).

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```bash
.venv/bin/python run.py
```

Then open <http://127.0.0.1:8000> in your browser.

## AI coach (optional)

The app is fully functional offline. The conversational coach is opt-in. Model
metadata lives in **`models.json`** (base URL, model name, roles); **keys live
in `.env`** (gitignored) or your OS environment. The coach panel has a model
selector, so you can switch between your providers.

1. Edit `models.json` with your OpenAI-compatible endpoints (`apiBase`,
   `model`, `apiKeyEnv`).
2. Put the keys in `.env`:
   ```env
   ALBERT_API_KEY=...
   GEMMA_API_KEY=...
   ```
3. Restart and open **Coaching → Coach** (or Home).

A local **Ollama** entry is included (`ollama-local`, no key needed) as an
offline fallback.

Only **derived metrics** are sent (load, CTL/ATL/TSB, ACWR, intensity split,
VO2max, recent summaries) — never raw GPS trackpoints or coordinates. Keys are
resolved server-side and never sent to the browser.

See `docs/AI_MODELS.md` for fields, `chatPath`, roles and troubleshooting.

> Thinking models (e.g. `qwen3.5`) spend tokens on hidden reasoning before
> answering. Raise `maxTokens` for that model or use a non-thinking model.

## Project structure

```
open-running-coach/
├── data/                 # Your activity files (KMZ / GPX / TCX)
├── coach.db              # SQLite database (notes, goals) — created automatically
├── .env.example          # Optional LLM coach configuration
├── run.py                # Server launcher
├── requirements.txt
└── app/
    ├── main.py           # FastAPI app + API routes
    ├── parsers/          # Format parsers (kmz.py, gpx.py, tcx.py, model.py)
    ├── connectors/       # External imports (OpenNutriTracker, generic CSV/JSON)
    ├── activity.py       # Basic statistics (distance, pace, elevation)
    ├── analysis.py       # Advanced analyses (splits, laps, zones, GAP, records…)
    ├── coaching.py       # Coaching analytics (load, fitness, ACWR, 80/20, VO2max, plans)
    ├── coach_llm.py      # Optional LLM coach (prompt + provider call)
    ├── store.py          # SQLite persistence (notes, goals, profile, RPE, feedback, sessions, plans)
    ├── config.py         # Configuration (pace zones, GAP, coaching models…)
    └── static/           # Frontend (HTML/CSS/JS + vendored Leaflet)
```

## API

| Method | Route | Description |
| --- | --- | --- |
| GET | `/api/summary` | Global totals (runs, distance, time, elevation) |
| GET | `/api/activities` | List of runs (summary) |
| GET | `/api/activities/{id}` | Full detail (trackpoints + markers + analyses) |
| PUT | `/api/activities/{id}/note` | Save a run's note |
| GET | `/api/heatmap` | Points of all routes (heatmap) |
| GET | `/api/best-efforts` | All-time best efforts over reference distances |
| GET | `/api/matched-runs` | Groups of identical routes |
| GET | `/api/monthly` | Monthly statistics + comparison |
| GET/POST | `/api/goals` | List / create a goal |
| PUT/DELETE | `/api/goals/{id}` | Update / delete a goal |
| PUT | `/api/activities/{id}/rpe` | Set/clear a run's RPE (1–10) |
| GET | `/api/coaching/load` | Daily training-load series |
| GET | `/api/coaching/fitness` | CTL / ATL / Form (TSB) series |
| GET | `/api/coaching/acwr` | Injury risk (ACWR) series |
| GET | `/api/coaching/intensity` | Intensity distribution (80/10/10 target) |
| GET | `/api/coaching/vo2max` | Effective VO2max + race predictions |
| GET/POST | `/api/coaching/plans` | List / generate a training plan |
| GET/DELETE | `/api/coaching/plans/{id}` | Get / delete a training plan |
| GET/PUT | `/api/activities/{id}/feedback` | Get / save post-run feedback (+ RPE) |
| GET/POST | `/api/sessions` | List / create support sessions |
| PUT/DELETE | `/api/sessions/{id}` | Update / delete a support session |
| GET | `/api/nutrition` | List fuel & recovery check-ins |
| PUT | `/api/nutrition/{date}` | Upsert a daily check-in |
| DELETE | `/api/nutrition/{id}` | Delete a check-in |
| GET/POST | `/api/supplements` | List / add supplements |
| PUT/DELETE | `/api/supplements/{id}` | Update / delete a supplement |
| GET | `/api/coaching/insights` | Rule-based insight cards (offline) |
| GET | `/api/coaching/chat/status` | Whether the LLM coach is configured |
| POST | `/api/coaching/chat` | Ask the coach (session history in the body) |
| POST | `/api/coaching/review` | Generate a structured weekly review |
| POST | `/api/reload` | Re-read the `data/` folder |

## Data format

The app reads three formats and normalises them all to the same internal model:

- **KMZ** (OpenTracks) — a ZIP containing `doc.kml`; trackpoints, speed,
  heart rate, cadence, point type, segments and markers.
- **GPX** — universal export (Strava "Download my data" gives one `.gpx` per
  activity). Trackpoints, elevation, time, heart rate/cadence from extensions;
  `<trkseg>` maps to segments. Strava's numeric `<type>` codes are mapped
  (9 → running, 12 → trail running).
- **TCX** (Garmin) — explicit `<Lap>` elements map directly to segments;
  `<Sport>` maps to the activity type; heart rate, cadence and speed.

When the same run is present in several files (e.g. OpenTracks KMZ *and* a
Strava GPX), a fingerprint (first/last GPS timestamps + distance) deduplicates
them, keeping the richest copy. Formats without a speed array (GPX) fall back
to positional speed for moving-time detection.

> Heart rate and cadence are often absent; the app only displays them when
> present. **FIT** is not yet supported (planned for later).

## Data folders & external connectors

Data is split by domain:

```
data/
├── running/     # KMZ / GPX / TCX (OpenTracks, Strava, Garmin)
├── workout/     # strength / mobility / cross-training exports
└── nutrition/   # nutrition exports (daily macros + weight)
```

Drop files in the matching folder and reload. Imports are **idempotent**: each
file is tracked, so re-importing an unchanged file does nothing.

### Recommended open-source apps (F-Droid first)

| Domain | F-Droid option | Notes |
|---|---|---|
| **Nutrition** | **Waistline** | On F-Droid (GPL-3). **OpenNutriTracker** has the cleaner, documented JSON export but is **not on F-Droid yet** — install it from **GitHub Releases** (e.g. via **Obtainium**, which is on F-Droid) or Google Play. |
| **Workout** | **wger** | On F-Droid, self-hostable, with a REST API. |

> The OpenNutriTracker connector below works with the app regardless of how you
> install it (GitHub APK, Obtainium or Play Store). Waistline's diary CSV uses
> `;` separators with localised headers, so it needs a dedicated adapter.

### Nutrition — OpenNutriTracker

Export from **Settings → Export / Import App Data → Export** (JSON or CSV
bundle) and put the `.zip` in `data/nutrition/`. The connector reads
`user_tracked_day` (daily kcal / protein / carbs / fat) and `weight_log`
(weight history). It only writes the macros and weights, so manual check-in
fields are preserved.

A generic CSV is also accepted (`,` or `;`, English or French headers, ISO
or `DD/MM/YYYY` dates, optional unit suffixes):

```csv
Date;Calories (kcal);Protéines (g);Glucides (g);Lipides (g);Poids (kg)
20/10/2026;2100;120;260;70;72,4
```

That is the **Waistline** diary-export style (semicolon + French headers +
decimal comma), so Waistline works without a per-app adapter.

### Workout — generic CSV/JSON

Export or map any workout app to this CSV (or a JSON list with the same
fields) and put it in `data/workout/`:

```csv
date,kind,title,duration_min,rpe,focus,notes,status
2026-10-21,strength,Upper body,45,6,shoulders|triceps,Imported,completed
2026-10-23,mobility,Hips and calves,20,2,hip|calves,,completed
```

- `kind`: strength · mobility · cross · rest · physio · other
- `focus`: pipe-separated body areas
- `status`: planned · completed · skipped

A **wger-style JSON** is also accepted:

```json
{ "workouts": [ { "name": "Upper body", "sessions": [
  { "date": "2026-10-20", "duration_min": 45, "rpe": 6,
    "focus": ["shoulders", "triceps"],
    "exercises": [ { "name": "Bench press", "sets": 3, "reps": 8, "weight_kg": 60 } ] }
] } ] }
```

`exercises` are summarized into the session notes (e.g. "Bench press 3x8 @ 60 kg").

Sample files are included so you can see the result immediately:
`examples/nutrition/waistline-sample.csv` and
`examples/workout/wger-sample.json` — copy them into the matching `data/`
folder to try them. Sessions appear in the **Planner**. Re-importing a changed
file replaces the sessions it previously created.

## Development

```bash
.venv/bin/pip install -r requirements-dev.txt   # pytest + ruff
.venv/bin/python -m pytest                      # test suite
.venv/bin/ruff check .                          # lint
.venv/bin/ruff format --check .                 # formatting
```

The suite covers the coaching models (load, CTL/ATL/TSB, ACWR, intensity, VDOT,
Riegel, plans), the analysis layer (zones, GAP, splits, GPS robustness, matched
runs), every parser and every connector.

**No real activity data is used.** All fixtures are generated from
`tests/fixtures/`:

| Fixture | Reproduces |
| --- | --- |
| `make_gpx.py` | Strava export: numeric `<type>`, no speed sensor, nested HR extension |
| `make_tcx.py` | Garmin export: one `<Lap>` per lap, `HeartRateBpm`, `TPX/Speed` |
| `make_kmz.py` | OpenTracks export: `<MultiTrack>`, parallel arrays, `IDLE` samples, no HR |
| `make_nutrition.py` | Waistline CSV (French headers, decimal comma) and JSON: meals, steps, weight |
| `make_workout.py` | wger JSON and generic CSV: sessions with exercise summaries |
| `track.py` | One canonical run rendered into all three activity formats |

`test_formats.py` parses the *same run* from GPX, TCX and KMZ and asserts that
distance, moving time, pace zones and GAP agree, so a parser cannot drift away
from the shared `Activity` model.

To try the app on synthetic data in a fresh clone:

```bash
.venv/bin/python examples/make_demo_data.py
```

It writes 5 activities across the three formats plus nutrition, weight, steps
and workouts into `data/`. Delete those files when you switch to real data.

CI (`.github/workflows/ci.yml`) runs three jobs: lint and format, the suite on
Python 3.11–3.14, and a smoke job that generates the demo dataset, boots
uvicorn and probes every API endpoint.

## Documentation

- `docs/GETTING_STARTED.md` — quick start for beta testers
- `docs/USER_MANUAL.md` — how to use the app (for beta testers)
- `docs/AI_MODELS.md` — model registry (`models.json`) and key handling
- `docs/DEPLOYMENT.md` — packaging as a standalone local app
- `docs/SALES_PROPOSAL_B2C.md` / `docs/SALES_PROPOSAL_B2B.md` — product proposals

## Notes & limitations

- **Distance**: the computation rejects aberrant GPS jumps (implied speed
  > 10 m/s) and falls back to the distance integrated from the recorded speed,
  which is more reliable. Some activities contain positional noise that can
  still slightly inflate the distance.
- **Elevation & GAP**: GPS altitude is noisy; it is smoothed before computing.
  The GAP relies on a simplified model (linear correction per % of grade) and
  remains an estimate.
- **Pace zones**: "standard" bounds (adjustable in `app/config.py`,
  `PACE_ZONES`) as long as heart-rate data is unavailable.
- **Matched runs**: heuristic detection (grid similarity + distance); it may
  group two close-but-not-identical routes.

## License

Released under the **GNU Affero General Public License v3.0** — see
[`LICENSE`](LICENSE) for the full text.

In short: you may use, study, modify and redistribute this software, including
commercially, provided that derivative works stay under the same license and
that anyone interacting with a modified version over a network is offered its
source code.

Third-party components bundled in `app/static/vendor/` keep their own
licenses (Leaflet: BSD-2-Clause, Leaflet.heat/simpleheat: MIT) — see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

Copyright (c) 2026 Mathis Certenais.

