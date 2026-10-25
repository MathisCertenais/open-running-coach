# open-running-coach

Local-first running intelligence. Reads GPS activity files from `data/running/`
(OpenTracks **KMZ**, **GPX**, **TCX**), computes statistics and coaching metrics,
and renders them in a vanilla HTML/CSS/JS interface served by FastAPI on
`127.0.0.1`. One user, one machine, no accounts, no telemetry.

## Run

```bash
.venv/bin/python run.py          # http://127.0.0.1:8000
.venv/bin/python -m pytest       # test suite
```

## Layout

| Path | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI routes and JSON API |
| `app/config.py` | **All tunable constants** (pace zones, GAP, ACWR bands, plan parameters) |
| `app/activity.py` | Basic statistics: distance, pace, elevation, moving time |
| `app/analysis.py` | Splits, laps, pace zones, GAP, best efforts, matched runs, monthly stats |
| `app/coaching.py` | Training load, CTL/ATL/TSB, ACWR, 80/20, VO2max, race prediction, plan generation |
| `app/store.py` | SQLite persistence (stdlib `sqlite3`) |
| `app/parsers/` | Format parsers sharing one `Activity` / `TrackPoint` model |
| `app/connectors/` | File-based imports (OpenNutriTracker, wger-style JSON) |
| `app/coach_llm.py` | Opt-in multi-model LLM client |
| `app/static/` | Frontend: `index.html`, `style.css`, `app.js`, vendored Leaflet |

## Hard rules

- **English only** — code, comments, docstrings, UI text, commit messages.
- **Runtime dependencies**: `fastapi` and `uvicorn`. Nothing else. Prefer the
  standard library. Dev-only tooling lives in `requirements-dev.txt`.
- **Tunable constants belong in `app/config.py`**, never inline in logic.
- **No frontend framework, no build step.** Vanilla JS, ES modules not required,
  vendored libraries only.
- **Local-first**: no network calls at runtime except map tiles and the
  explicitly opt-in LLM coach. API keys come from environment variables and are
  never written to the database or sent to the browser.
- **Accessibility is a product requirement**, not a polish pass: WCAG 2.1 AA
  minimum. Keyboard reachable, visible focus, labelled controls, no
  colour-only meaning.

## Data quirks that must keep working

- Heart rate and cadence are declared in the OpenTracks schema but absent from
  current files. Every consumer must tolerate `None`.
- GPS position jumps exist. Use `step_distance()`, which rejects implied speeds
  above `MAX_IMPLIED_SPEED` and falls back to the speed sensor.
- GPS altitude is noisy. Smooth before computing grade or elevation.
- Distance is the robust step distance; moving time excludes `IDLE` points and
  gaps longer than `MAX_MOVING_GAP`.
- A `<Track>` is one manual segment (lap). Multiple tracks = interval session.

## Where to look before changing anything

- `GLOSSARY.md` — canonical vocabulary for every metric. Use these exact terms.
- `CODING_STANDARDS.md` — the rules a reviewer will enforce on your diff.
- `docs/adr/` — why the architecture is what it is. Do not "fix" a deliberate
  decision without reading the ADR that made it.
- `docs/research/` — literature notes backing the coaching formulas.

## Agent skills

### Issue tracker

GitHub Issues on `MathisCertenais/open-running-coach`, driven with the `gh` CLI.
See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical labels (`needs-triage`, `needs-info`, `ready-for-agent`,
`ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` plus `docs/adr/`. See `docs/agents/domain.md`.
