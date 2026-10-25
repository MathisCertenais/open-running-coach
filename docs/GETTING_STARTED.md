# Coach Running — Getting started

A quick guide for beta testers. Everything stays on your computer.

## 1. Open the app

- Double-click the app (or run the launcher). Your browser opens automatically.
- If it does not, open the URL printed in the launcher window.

## 2. Create your profile (once)

Enter your **name, birth date and height**. It is stored locally and only asked
once.

## 3. Add your runs

Put your activity files in `data/running/` and press **↻** (top right).

- **Strava** → export GPX.
- **Garmin** → export TCX or GPX.
- **OpenTracks** → KMZ.

## 4. Your home dashboard

The **Home** page gives you the essentials in order:

1. **Coaching** — all your KPIs in one column and the AI coach in the other.
2. **Schedule** — this week's sessions.
3. **Race history** — your runs and best efforts.
4. **Stats & profile** — volume, weight and goals.

## 5. Log your day (Fuel)

Open **Fuel** to record **steps**, hydration, energy, appetite and supplements.
Low daily steps trigger a **sedentary** warning, because low movement raises
injury risk.

## 6. Import nutrition and workouts (optional)

- **Waistline** → *Export Diary to CSV* → `data/nutrition/`.
- **wger** → JSON (`{"workouts": [...]}`) → `data/workout/`.
- Press **↻**.

## 7. AI coach (optional)

The app works fully offline. For the conversational coach, add a `.env` with a
local Ollama or an OpenAI-compatible endpoint (see `docs/DEPLOYMENT.md`).

## Where your data lives

- Packaged app: `~/CoachRunning/`.
- Development: the project folder.
- Back up that folder (it contains `coach.db` and `data/`).

## Need more detail?

See `docs/USER_MANUAL.md`.

> Coach Running is a training tool, not a medical device.
