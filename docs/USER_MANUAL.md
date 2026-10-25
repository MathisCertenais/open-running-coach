# Coach Running — User Manual

A local running and training dashboard. Everything stays on your computer.

## 1. First launch

1. Start the app (see **Deployment** for the packaged app, or run
   `.venv/bin/python run_app.py` in development).
2. Your browser opens on the app.
3. **Create your athlete profile** (name, birth date, height). This is stored
   locally and only asked once.

## 2. Your data folders

The app reads three folders. Drop files in and press the **↻** button (top
right) to import them.

```
data/
├── running/     # KMZ / GPX / TCX (OpenTracks, Strava, Garmin)
├── workout/     # strength / mobility / cross-training exports
└── nutrition/   # nutrition exports (macros, weight, steps)
```

Imports are **idempotent**: an unchanged file is never imported twice.

## 3. Activities (your runs)

- The left list shows all runs. Click one to open it.
- The map is coloured by speed; the legend is bottom-right.
- **Stats**: distance, moving time, pace, elevation, max speed.
- **Tabs**: Splits · Feedback · Laps · Pace zones · GAP.
- **Notes**: free text, saved per run.
- **Shoe**: assign a pair from the picker.

## 4. Planner (strength, mobility, rest)

- Open **Planner** to see the week: runs from your files + support sessions.
- **＋ Log session**: pick a date, kind (strength / mobility / cross-training /
  rest / physio / other), duration, RPE, focus areas (glutes, shoulders,
  triceps, calves…), notes, and status.
- **Done / Skip / Edit / ✕** on each session.
- Generated training plans automatically add ~2 strength + 2 mobility + 1 rest
  per week (less strength during the taper). They appear here and can be edited.

## 5. Fuel (nutrition, steps, supplements)

Open **Fuel**:

- **Daily check-in**: hydration, energy, appetite, **steps**, fueling
  before/during/after, notes.
- **Supplements**: add name, dose, frequency, and tick what you took.
- **Recent days**: shows steps, macros (kcal/P/C/F), hydration, supplements.
- **Steps** are manual for now. Low daily steps trigger a **sedentary** warning,
  because low daily movement is associated with higher injury risk.

> The manual check-in and imported data coexist: an import only fills the
> macros/steps, it never erases what you typed.

## 6. Importing from other apps

### Nutrition — Waistline (F-Droid) or a generic CSV

- **Waistline** → *Settings → Import/Export → Export Diary to CSV*.
- Put the CSV in `data/nutrition/` and press **↻**.
- The importer accepts `,` or `;`, English or French headers, ISO or
  `DD/MM/YYYY` dates, decimal comma, and optional units
  (`Calories (kcal)`, `Protéines (g)`, `Pas`).

### Nutrition — OpenNutriTracker

- *Settings → Export / Import App Data → Export* (JSON or CSV bundle).
- Put the `.zip` in `data/nutrition/` and press **↻**.
- Reads daily kcal/protein/carbs/fat and weight history.

### Workout — wger or a generic JSON/CSV

- Put a JSON like `{"workouts": [{"name": "...", "sessions": [...]}]}` or a CSV
  in `data/workout/` and press **↻**. `exercises` are summarized into the notes.

### Samples

Two sample files are included so you can see the result immediately:
`examples/nutrition/waistline-sample.csv` and
`examples/workout/wger-sample.json` — copy them into the matching `data/`
folder to try them. Delete them when you switch to real data; remove the
imported rows with the **✕** buttons in Fuel / Planner / Profile.

## 7. Coaching

Open **Coaching**:

- **Load & fitness** — daily load, CTL/ATL/TSB (fitness, fatigue, form).
- **Injury risk** — ACWR (7-day vs 28-day load) with alert bands.
- **Intensity (80/20)** — easy / moderate / hard time vs the polarised ideal
  (80% easy, 10% moderate, 10% hard).
- **VO2max & race** — effective VO2max and predicted race times.
- **Training plans** — periodized plan generator (race or weekly volume).
- **Coach** — rule-based insights + optional AI chat.

Every metric has a **"How is this computed?"** section.

## 8. AI coach (optional)

Add a `.env` file at the project root (see `.env.example`) with a local Ollama
or an OpenAI-compatible endpoint, then restart. Without it, the insight cards
still work offline.

## 9. Backup

- The database is `coach.db` (in the app folder, or `~/CoachRunning/` for the
  packaged app).
- Your activity files are in `data/`.
- Copy both to back up everything.

## 10. Troubleshooting

- **A file is not imported**: check the extension and the folder; press **↻**.
- **A run appears twice**: the same run in two sources is deduplicated
  automatically; if not, remove one file.
- **The AI coach says "not configured"**: check `.env` and restart.
- **The page does not open**: the app prints the URL; open it manually.

> Coach Running is a training tool, not a medical device.
