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
# Models added from the UI. Kept out of version control: it is user data.
LOCAL_MODELS_FILE = APP_HOME / "models.local.json"
# Where a key entered in the UI is written. Also gitignored, chmod 600.
ENV_FILE = APP_HOME / ".env"

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

# Grade-Adjusted Pace (GAP).
# The correction uses Minetti et al. (2002), "Energy cost of walking and running
# at extreme slopes", J Appl Physiol: the cost of running per metre rises with
# gradient and is fitted from -45% to +45%. The flat-equivalent speed is
#        v_flat = v * Cr(grade) / Cr(0)
# Grade is computed over at least GAP_WINDOW_M metres: a 1-3 m step carries more
# GPS altitude noise than slope.
GAP_WINDOW_M = 50.0
GAP_MAX_ABS_GRADE = 0.45  # outside Minetti's fitted range the grade is clamped
GAP_FACTOR_MIN = 0.45
GAP_FACTOR_MAX = 4.0

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

# Acute:chronic load ratio. Describes how fast load is changing; it is NOT a
# risk prediction (see docs/research/04-acwr.md and issue #5).
ACWR_ACUTE_DAYS = 7
ACWR_CHRONIC_DAYS = 28
# Bands: (name, lower_bound_inclusive, upper_bound_exclusive). None = unbounded.
# The labels describe the change, they do not judge the athlete.
ACWR_BANDS = [
    ("ramping_down", None, 0.8),
    ("steady", 0.8, 1.3),
    ("ramping_up", 1.3, 1.5),
    ("sharp_increase", 1.5, None),
]
# After this many days without a recorded activity the ratio is meaningless
# (a layoff would otherwise read as "ramping down").
ACWR_GAP_DAYS = 7
# The form band is hidden until the moving averages have enough history to mean
# anything: starting from zero makes a normal athlete look "fatigued" for months.
CTL_CALIBRATION_DAYS = 42

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
PLAN_DELOAD_FACTOR = 0.6  # deload week = 60% of the previous build week
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
# How many times the coach may call tools before it must answer.
LLM_MAX_TOOL_ROUNDS = int(os.environ.get("COACH_LLM_MAX_TOOL_ROUNDS", "4"))
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
# Conditions during the run. Heat is the most common reason a pace that felt
# hard looks easy on paper.
FEEDBACK_CONDITIONS = ("", "cool", "temperate", "warm", "hot", "humid")
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

# ---------------------------------------------------------------------------
# File uploads (drag and drop into the UI)
# ---------------------------------------------------------------------------
# Each data folder only accepts the formats its importer understands, so a file
# can never land somewhere nothing will read it.
UPLOAD_ALLOWED_EXTENSIONS = {
    "running": (".kmz", ".gpx", ".tcx"),
    "nutrition": (".csv", ".json", ".zip"),
    "workout": (".csv", ".json"),
}
UPLOAD_DIRECTORIES = {
    "running": DATA_RUNNING_DIR,
    "nutrition": DATA_NUTRITION_DIR,
    "workout": DATA_WORKOUT_DIR,
}
# Refuse anything larger than this: an activity export is a few MB at most, and
# reading an unbounded body into memory would be a denial-of-service vector.
UPLOAD_MAX_BYTES = 50 * 1024 * 1024

# ---------------------------------------------------------------------------
# Injury episodes and exercise correlation
# ---------------------------------------------------------------------------
# Two pain reports in the same place, less than this many days apart, belong to
# the same episode.
INJURY_EPISODE_GAP_DAYS = 21
# An episode with no report for this long is considered settled.
INJURY_ACTIVE_DAYS = 14
# How far back to look for a strength session that could explain a pain report.
INJURY_LOOKBACK_HOURS = 48
# Only sessions at least this hard are considered (1-10 RPE).
INJURY_SESSION_MIN_RPE = 7

# ---------------------------------------------------------------------------
# Automatic import
# ---------------------------------------------------------------------------
# How often the server looks for new files in data/. Set to 0 to disable the
# watcher and keep the manual reload button only. Ten seconds is imperceptible
# for a sync tool and costs one directory stat per folder.
DATA_WATCH_SECONDS = 10

# ---------------------------------------------------------------------------
# Load interpretation
# ---------------------------------------------------------------------------
# Session-RPE load and pace-based load are different scales. A ratio outside
# this band means the athlete found the session much harder (or easier) than the
# pace alone suggests: heat, fatigue, illness, or a bad day.
LOAD_DIVERGENCE_LOW = 0.7
LOAD_DIVERGENCE_HIGH = 1.4
# Ignore trivial sessions, where the ratio is meaningless.
LOAD_DIVERGENCE_MIN_LOAD = 15.0

# Rough load weight per running workout type, used only to project a plan:
# session load = duration_min x weight. Ordered like the pace-zone weights.
WORKOUT_LOAD_WEIGHTS = {
    "recovery": 1.0,
    "easy": 2.0,
    "long_run": 2.0,
    "tempo": 4.0,
    "intervals": 5.0,
}

# ---------------------------------------------------------------------------
# Critical speed and durability
# ---------------------------------------------------------------------------
# Performances used to fit the speed-duration model d = CS*t + D'. Very short
# efforts are dominated by acceleration, very long ones by fuelling.
CRITICAL_SPEED_MIN_S = 120.0
CRITICAL_SPEED_MAX_S = 3600.0
# A run must be at least this long before a fade index means anything.
FADE_MIN_DISTANCE_M = 8000.0
# Runs compared to report a trend.
FADE_TREND_RUNS = 5
