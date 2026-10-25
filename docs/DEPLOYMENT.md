# Deployment — installable local app for non-developers

The goal: Florian downloads one file, double-clicks, and the app opens in his
browser — no Python, no terminal.

## Recommended: PyInstaller standalone app

PyInstaller bundles Python, FastAPI/Uvicorn and the static frontend into a
self-contained folder (plus `CoachRunning.app` on macOS). It does **not**
cross-compile: build on the OS you want to ship.

### Already prepared in this repo

- `run_app.py` — picks a free port, opens the default browser, runs Uvicorn.
- `app/config.py` — when frozen, user data lives in `~/CoachRunning/`
  (`data/`, `coach.db`, `.env`) and static assets come from the bundle.
- Data folders are created automatically on first run.
- `open-running-coach.spec` — PyInstaller spec (bundles `app/static` as `static`).

### Build (macOS)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pyinstaller
.venv/bin/pyinstaller open-running-coach.spec
open dist/CoachRunning.app          # or: dist/CoachRunning/CoachRunning
```

### Build (Windows)

```powershell
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt pyinstaller
.venv\Scripts\pyinstaller open-running-coach.spec
dist\CoachRunning\CoachRunning.exe
```

### Build (Linux)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pyinstaller
.venv/bin/pyinstaller open-running-coach.spec
./dist/CoachRunning/CoachRunning
```

## Distribution

- **macOS**: zip `CoachRunning.app`. For a private beta, the tester can
  right-click → **Open** to bypass Gatekeeper. For public distribution, sign
  and notarize the app.
- **Windows**: zip the `dist/CoachRunning/` folder. SmartScreen shows
  "More info → Run anyway" until the binary is code-signed.
- **Linux**: tar.gz the folder.

## First run

1. The app creates `~/CoachRunning/data/{running,workout,nutrition}` and
   `coach.db`.
2. The browser opens automatically (a free port, e.g. 51234).
3. The onboarding asks for name, birth date and height — once, stored locally.

## Optional AI coach

The app works fully offline. To enable the conversational coach, put a `.env`
in `~/CoachRunning/`:

```env
COACH_LLM_BASE_URL=http://127.0.0.1:11434/v1
COACH_LLM_MODEL=qwen2.5:7b-instruct
```

with Ollama running locally. Leave it unset to stay offline (insight cards still
work).

## Alternatives considered

| Option | Verdict |
|---|---|
| **PyInstaller** | ✅ Recommended: no runtime for the user, native-ish, simple. |
| **Docker** | Requires Docker Desktop; not suitable for non-developers. |
| **Briefcase / Tauri / Electron** | More work; Tauri/Electron add a JS toolchain. Good later if you want a real window and auto-update. |
| **`.command` / `.bat` + Python** | Requires the user to install Python; not "double-click" friendly. |

## Beta-test checklist (Florian)

- [ ] Build the macOS app and test on a clean Mac (no Python).
- [ ] Verify first-run profile + sample import (Waistline/wger).
- [ ] Confirm the browser opens and the app is usable without a terminal.
- [ ] Decide the backup story: `~/CoachRunning/` is the single folder to back up.
- [ ] Collect feedback on the Fuel/Planner flows.
