"""Central configuration for the Coach Running application."""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# When packaged as a standalone app, keep user data in a writable home folder
# (the bundle itself is read-only on macOS/Windows). In development, use the
# project folder as before.
if getattr(sys, "frozen", False):
    APP_HOME = Path.home() / "CoachRunning"
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
else:
    APP_HOME = BASE_DIR
    RESOURCE_DIR = Path(__file__).resolve().parent

DATA_DIR = APP_HOME / "data"
DATA_RUNNING_DIR = DATA_DIR / "running"
DATA_WORKOUT_DIR = DATA_DIR / "workout"
DATA_NUTRITION_DIR = DATA_DIR / "nutrition"

# SQLite database (notes, goals, and future coaching data)
DB_PATH = APP_HOME / "coach.db"

# Non-secret model registry: base URLs, model names, and the *name* of the env
# var holding each key (never the key itself).
MODELS_FILE = APP_HOME / "models.json"

# Folder of static assets served by the web server
STATIC_DIR = RESOURCE_DIR / "static"


def _load_dotenv() -> None:
    """Load an optional local .env file (KEY=value) without extra dependencies.

    Existing environment variables take precedence, so shell overrides win.
    """
    env_path = APP_HOME / ".env"
    if not env_path.exists():
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

# Speed threshold (m/s) below which a point is considered stationary
MOVING_SPEED_THRESHOLD = 0.3

# Maximum time (s) between two points to count as "moving" time
# (ignores large gaps without GPS points)
MAX_MOVING_GAP = 120.0

# ---------------------------------------------------------------------------
# Advanced analysis
# ---------------------------------------------------------------------------

# Reference distances for records / best efforts (meters)
BEST_EFFORT_DISTANCES = [
    (400, "400 m"),
    (1000, "1 km"),
    (1609, "1 mile"),
    (5000, "5 km"),
    (10000, "10 km"),
    (21097, "Half marathon"),
    (42195, "Marathon"),
]

# Pace zones (s/km). Bounds: min <= pace < max.
# Default "standard" zones; adjustable to the athlete's level.
PACE_ZONES = [
    {"name": "Z1 Recovery", "min": 390, "max": None, "color": "#94a3b8"},
    {"name": "Z2 Endurance", "min": 330, "max": 390, "color": "#3b82f6"},
    {"name": "Z3 Tempo", "min": 290, "max": 330, "color": "#10b981"},
    {"name": "Z4 Threshold", "min": 260, "max": 290, "color": "#f59e0b"},
    {"name": "Z5 VO2max", "min": 230, "max": 260, "color": "#f97316"},
    {"name": "Z6 Sprint", "min": 0, "max": 230, "color": "#ef4444"},
]

# Grade-Adjusted Pace (GAP) parameters — simplified model.
# Correction factor per % of grade (e.g. 3.0 => +3% of "equivalent" speed per %
# of uphill grade). Descents are capped at GAP_MAX_DOWN_GRADE.
GAP_UPHILL_FACTOR = 3.0
GAP_DOWNHILL_FACTOR = 0.5
GAP_MAX_DOWN_GRADE = 0.15  # 15%

# Matched runs: detection of identical routes.
MATCH_CELL_DEG = 0.0008  # grid cell size (~60-90 m)
MATCH_JACCARD_THRESHOLD = 0.55  # minimum similarity (intersection/union)
MATCH_DISTANCE_RATIO = 0.25  # tolerated distance difference (25%)

# ---------------------------------------------------------------------------
# Coaching — training load & fitness (Banister / Coggan)
# ---------------------------------------------------------------------------

# Pace-zone weights for the pace-based load (Banister-TRIMP analog on pace).
# Zone index i -> weight i+1 (Z1 Recovery = 1 ... Z6 Sprint = 6).
PACE_ZONE_WEIGHTS = [1, 2, 3, 4, 5, 6]

# CTL / ATL time constants (days) — Coggan Performance Management Chart.
CTL_TAU_DAYS = 42.0
ATL_TAU_DAYS = 7.0

# Form (TSB) is "fresh" above this, "fatigued" below -this, neutral in between.
FORM_NEUTRAL_BAND = 5.0

# Acute:Chronic Workload Ratio (Gabbett 2016).
ACWR_ACUTE_DAYS = 7
ACWR_CHRONIC_DAYS = 28
# Bands: (name, lower_bound_inclusive, upper_bound_exclusive). None = unbounded.
ACWR_BANDS = [
    ("undertraining", None, 0.8),
    ("sweet_spot", 0.8, 1.3),
    ("caution", 1.3, 1.5),
    ("high_risk", 1.5, None),
]

# Intensity distribution (Seiler 2010 polarized training). Groups of pace zones
# (0-based indices): easy = Z1+Z2, moderate = Z3, hard = Z4+Z5+Z6.
INTENSITY_GROUPS = {
    "easy": {"zones": [0, 1], "color": "#3b82f6"},
    "moderate": {"zones": [2], "color": "#10b981"},
    "hard": {"zones": [3, 4, 5], "color": "#f97316"},
}
# Polarized ideal (80/20): ~80% easy; the remaining ~20% should favour hard work
# over the "grey zone" moderate, so we target 80/10/10.
INTENSITY_TARGET = {"easy": 0.80, "moderate": 0.10, "hard": 0.10}
INTENSITY_WEEKLY_DAYS = 7
INTENSITY_ROLLING_DAYS = 28

# VO2max & race prediction.
# Riegel exponent: T2 = T1 * (D2 / D1)^RIEGEL_EXPONENT.
RIEGEL_EXPONENT = 1.06
# Target distances for race-time prediction (meters, label).
RACE_DISTANCES = [
    (400, "400 m"),
    (1000, "1 km"),
    (5000, "5 km"),
    (10000, "10 km"),
    (21097, "Half marathon"),
    (42195, "Marathon"),
]

# Plan generation (periodization).
PLAN_PROGRESSION = 1.10  # +10% weekly volume between weeks
PLAN_DELOAD_EVERY = 4  # deload every 4th week
PLAN_DELOAD_FACTOR = 0.6  # deload week = 60% of the projected volume
PLAN_RAMP_START = 0.6  # first week starts at 60% of the peak volume
PLAN_EASY_FRACTION = 0.80  # 80/20 distribution
PLAN_HARD_FRACTION = 0.20
PLAN_LONG_RUN_FRACTION = 0.28  # long run ≈ 28% of the weekly volume
PLAN_DEFAULT_WEEKS = 12
PLAN_MAX_WEEKS = 24
PLAN_DEFAULT_SESSIONS = 4
PLAN_MIN_SESSIONS = 3
PLAN_MAX_SESSIONS = 6
PLAN_DEFAULT_WEEKLY_MIN = 180.0  # fallback weekly volume (minutes) when no data
# Representative pace (s/km) per workout type, derived from PACE_ZONES midpoints.
WORKOUT_PACES = {
    "recovery": 420,  # Z1 (~7:00/km)
    "easy": 360,  # Z2 (~6:00/km)
    "long_run": 360,  # Z2 (~6:00/km)
    "tempo": 275,  # Z3–Z4 (~4:35/km)
    "intervals": 245,  # Z4–Z5 (~4:05/km)
}
# Pace zone labels per workout type (for the plan UI).
WORKOUT_ZONES = {
    "recovery": "Z1",
    "easy": "Z2",
    "long_run": "Z2",
    "tempo": "Z3–Z4",
    "intervals": "Z4–Z5",
}
# Suggested peak weekly volume (km) per race distance, used as a floor when the
# athlete has too little recent data to infer volume from history.
RACE_WEEKLY_VOLUME_KM = {
    400: 25,
    1000: 25,
    5000: 30,
    10000: 45,
    21097: 60,
    42195: 85,
}

# ---------------------------------------------------------------------------
# Coaching — optional LLM assistant (opt-in)
# ---------------------------------------------------------------------------
# The coach is only enabled when COACH_LLM_BASE_URL and/or COACH_LLM_API_KEY are
# set. When unset, the app stays fully local and only the deterministic insight
# cards are available. Point the base URL at a local Ollama / LM Studio server
# (e.g. http://127.0.0.1:11434/v1) to keep all data on the machine.
_LLM_BASE_URL_ENV = os.environ.get("COACH_LLM_BASE_URL")
_LLM_API_KEY_ENV = os.environ.get("COACH_LLM_API_KEY")

LLM_BASE_URL = _LLM_BASE_URL_ENV or "https://api.openai.com/v1"
LLM_API_KEY = _LLM_API_KEY_ENV or ""
LLM_MODEL = os.environ.get("COACH_LLM_MODEL", "gpt-4o-mini")
LLM_ENABLED = bool(_LLM_BASE_URL_ENV or _LLM_API_KEY_ENV)
LLM_TIMEOUT_S = float(os.environ.get("COACH_LLM_TIMEOUT_S", "60"))
LLM_MAX_TOKENS = int(os.environ.get("COACH_LLM_MAX_TOKENS", "900"))
LLM_TEMPERATURE = float(os.environ.get("COACH_LLM_TEMPERATURE", "0.4"))
LLM_HISTORY_TURNS = int(os.environ.get("COACH_LLM_HISTORY_TURNS", "8"))
LLM_CONTEXT_MAX_CHARS = int(os.environ.get("COACH_LLM_CONTEXT_MAX_CHARS", "14000"))

# ---------------------------------------------------------------------------
# Post-run feedback (subjective enrichment of a run)
# ---------------------------------------------------------------------------
FEEDBACK_SESSION_TYPES = (
    "recovery",
    "easy",
    "long",
    "tempo",
    "intervals",
    "race",
    "other",
)
FEEDBACK_SURFACES = ("road", "trail", "track", "treadmill", "mixed")
FEEDBACK_COMPLETION = ("full", "partial", "aborted")
FEEDBACK_PAIN_LOCATIONS = (
    "knee",
    "shin",
    "calf",
    "achilles",
    "foot",
    "ankle",
    "hip",
    "hamstring",
    "quad",
    "back",
    "other",
)
FEEDBACK_PAIN_SIDES = ("left", "right", "both")
FEEDBACK_PAIN_TIMINGS = ("during", "after", "next_morning", "multiple")
FEEDBACK_PAIN_TRENDS = ("better", "same", "worse")
FEEDBACK_SCALE_MIN = 1
FEEDBACK_SCALE_MAX = 5
FEEDBACK_PAIN_SEVERITY_MAX = 10

# ---------------------------------------------------------------------------
# Support sessions (strength, mobility, cross-training, rest)
# ---------------------------------------------------------------------------
SESSION_KINDS = ("strength", "mobility", "cross", "rest", "physio", "other")
SESSION_STATUS = ("planned", "completed", "skipped")
SESSION_BODY_AREAS = (
    # lower body
    "glutes",
    "quads",
    "hamstrings",
    "calves",
    "achilles",
    "hip",
    "hip_flexors",
    "adductors",
    "abductors",
    "ankle",
    "foot",
    # core / trunk
    "core",
    "obliques",
    "back",
    # upper body
    "chest",
    "shoulders",
    "biceps",
    "triceps",
    "forearms",
    "lats",
    "neck",
)
# Relative load weight per kind: support_load = RPE x minutes x weight.
# Kept separate from the running load so ACWR stays running-only.
SUPPORT_LOAD_WEIGHTS = {
    "strength": 0.6,
    "mobility": 0.2,
    "cross": 0.8,
    "rest": 0.0,
    "physio": 0.2,
    "other": 0.4,
}
# Default support sessions inserted by the plan generator (day_offset 0 = Mon).
PLAN_SUPPORT_DEFAULTS = (
    {
        "kind": "rest",
        "day_offset": 0,
        "duration_min": 0,
        "rpe": 0,
        "title": "Rest day",
        "focus": (),
    },
    {
        "kind": "strength",
        "day_offset": 1,
        "duration_min": 45,
        "rpe": 6,
        "title": "Strength: lower body + core",
        "focus": ("glutes", "core", "hamstrings"),
    },
    {
        "kind": "mobility",
        "day_offset": 2,
        "duration_min": 20,
        "rpe": 2,
        "title": "Mobility: hips + ankles",
        "focus": ("hip", "ankle"),
    },
    {
        "kind": "strength",
        "day_offset": 4,
        "duration_min": 40,
        "rpe": 5,
        "title": "Strength: posterior chain + calves",
        "focus": ("glutes", "calves", "back"),
    },
    {
        "kind": "mobility",
        "day_offset": 5,
        "duration_min": 20,
        "rpe": 2,
        "title": "Mobility: calves + feet",
        "focus": ("calves", "foot"),
    },
)

# ---------------------------------------------------------------------------
# Fuel & recovery (optional daily check-in)
# ---------------------------------------------------------------------------
NUTRITION_ENERGY_MIN = 1
NUTRITION_ENERGY_MAX = 5
NUTRITION_HYDRATION_MAX_L = 10.0
SUPPLEMENT_FREQUENCIES = (
    "daily",
    "5x_week",
    "3x_week",
    "2x_week",
    "weekly",
    "as_needed",
)
# A weight loss faster than this (% of body weight per week) is flagged.
WEIGHT_LOSS_WARN_PCT_PER_WEEK = 1.0
# Daily steps: below these thresholds the athlete is considered sedentary.
STEPS_SEDENTARY_WARN = 5000
STEPS_SEDENTARY_HIGH = 2500
