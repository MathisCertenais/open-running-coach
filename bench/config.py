"""Benchmark-only constants.

Values that change how a measurement is taken live here: paths, repeats, caps,
timeouts and price-table metadata. Anything that changes product behaviour is
read from ``app.config`` and never restated, so the harness cannot drift from
the app it measures.
"""

from __future__ import annotations

from pathlib import Path

from app.config import LLM_TIMEOUT_S

# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------
BENCH_ROOT = Path(__file__).resolve().parent
REPO_ROOT = BENCH_ROOT.parent
FIXTURES_DIR = BENCH_ROOT / "fixtures"
SNAPSHOTS_DIR = FIXTURES_DIR / "snapshots"
TOOL_CONTEXT_DIR = FIXTURES_DIR / "tool_context"
PROMPTS_FILE = FIXTURES_DIR / "prompts.json"
ROSTER_FILE = BENCH_ROOT / "models.json"
DATA_ROOT = BENCH_ROOT / "data"
TMP_DIRNAME = "tmp"

SWEEPS_DIRNAME = "sweeps"
RECORDS_FILENAME = "records.jsonl"
SCORES_FILENAME = "scores.jsonl"
META_FILENAME = "meta.json"
REPORT_MARKDOWN = "report.md"
REPORT_JSON = "report.json"
RAW_DIRNAME = "raw"

# ---------------------------------------------------------------------------
# Versions and defaults
# ---------------------------------------------------------------------------
FIXTURE_VERSION = 1
BENCH_SCHEMA_VERSION = 1
PRICE_TABLE_VERSION = 1
DEFAULT_SWEEP = "default"
DEFAULT_REPEATS = 3
DEFAULT_SEED = 0
# Deterministic record ids are this many hex characters, as in the spec example.
RECORD_ID_CHARS = 16
# Reading the git sha for meta.json must never hang a sweep.
GIT_TIMEOUT_S = 5

# The harness may override production's timeout; it may not change any other
# request setting, which must stay what the app actually uses.
DEFAULT_TIMEOUT_S = LLM_TIMEOUT_S

# ---------------------------------------------------------------------------
# Caps
# ---------------------------------------------------------------------------
# Tool results are stored as a hash plus this many characters of preview.
BENCH_PREVIEW_CHARS = 400
# A dry run has no token counts, so it prints a rough upper-bound estimate.
DRY_RUN_ESTIMATE_PROMPT_TOKENS = 6_000
DRY_RUN_ESTIMATE_COMPLETION_TOKENS = 450
# Longest stderr tail kept in a CLI diagnostic record.
CLI_STDERR_TAIL_CHARS = 1_000

# ---------------------------------------------------------------------------
# Scoring thresholds (used by the scoring phase, kept here so the capture
# metadata and the report read one number).
# ---------------------------------------------------------------------------
BENCH_MIN_ANSWERS = 45
BENCH_MIN_CELLS = 15
WILSON_Z_95 = 1.959963984540054

# Number-matching tolerances, transcribed from rubric §4.2.1. Percent, ratio and
# count live next to the class they belong to because they are not symmetric;
# the rest are here so a change is reviewed in one place.
GROUNDING_PERCENT_TOLERANCE = 1.0
GROUNDING_RATIO_TOLERANCE = 0.05
GROUNDING_PACE_TOLERANCE_S = 5.0
GROUNDING_DURATION_TOLERANCE_S = 15.0
GROUNDING_DISTANCE_TOLERANCE_M = 100.0
GROUNDING_PREDICTION_TOLERANCE = 0.01
# An estimate rounded to the minute is still the same estimate (rubric §10.1).
GROUNDING_ROUNDING_ALLOWANCE_S = 30.0

# Rubric §6: an intensity share within this many points of target is on target.
INTENSITY_TARGET_TOLERANCE_PCT = 5.0
# Rubric §4.4 I-05: a deviation this small is noise, not a finding.
INTENSITY_NOISE_BAND_PCT = 3.0
# Rubric §4.1 S-03.
ANSWER_MIN_WORDS = 50
ANSWER_MAX_WORDS = 450
ANSWER_SOFT_WORDS = 350
ANSWER_FAIL_WORDS = 600
# Rubric §4.1 S-01 (as amended in §12.2): an anti-empty-template floor, not a
# length target. Assessment is explicitly allowed to be one line.
SECTION_MIN_WORDS = 4
# Rubric §12.3.3: P-01 deducts one major unit per missing element, capped at two.
P01_MAX_MAJOR_UNITS = 2
# Rubric §4.6 X-01 / §4.5 R-05: how close a pain report makes a fixture live.
ACTIVE_PAIN_WINDOW_DAYS = 7

# Rubric §9.1 weights, applied to the composite.
COMPOSITE_WEIGHT_R = 0.45
COMPOSITE_WEIGHT_COVERAGE = 0.25
COMPOSITE_WEIGHT_JUDGE = 0.30
GATE_MIN_R = 70
POINTS_PER_MAJOR = 25
POINTS_PER_MINOR = 5
JUDGE_MIN = 1
JUDGE_MAX = 5
# Rubric §9.2 condition 3: the sign-test bar at n = 15.
SIGN_TEST_MIN_WIN_SHARE = 0.8

# Rubric §1.2: names the constant block transcribed into rubric.json. The loader
# resolves the symbolic name so no check carries its own copy.
RUBRIC_CONSTANTS_KEY = "rubric_section_1_2"

# ---------------------------------------------------------------------------
# Judge (rubric §8, §12.5). The prompt, anchors and weights are transcribed in
# rubric.json's ``judge`` block; only the transport and retry knobs live here.
# ---------------------------------------------------------------------------
JUDGE_CALIBRATION_FILENAME = "judge_calibration.v1.json"
JUDGE_CALLS_PER_ANSWER = 3
JUDGE_EXTRA_CALLS = 1
JUDGE_UNSTABLE_SPAN = 2
JUDGE_TEMPERATURE = 0.0
# Output budget for one judge reply. The first real run lost every reply from
# the thinking model to hidden reasoning at 700 tokens; 1,500 leaves room for a
# JSON object plus a reasoning pass. This is a transport knob, not a rubric
# threshold: rubric.json's "max_tokens" is treated as a floor, not a ceiling.
JUDGE_MAX_TOKENS = 1_500
# A reasoning-only reply is retried once with twice the budget, capped here so
# a runaway model cannot spend unbounded output tokens on one cell.
JUDGE_MAX_TOKENS_CEILING = 3_000
# One retry per reply: extraction failure, reasoning-only, or a schema/contract
# violation each get exactly one second chance, then the cell is invalid.
JUDGE_REPLY_ATTEMPTS = 2
# The retry prompt required by rubric practice: no prose, no fence.
JUDGE_STRONGER_INSTRUCTION = "Output only the JSON object, no prose, no code fence."
# A dimension scored 1 or 5 must carry a rationale of at least this many words:
# the machine-checkable replacement for "quotes or names a span".
JUDGE_EXTREME_RATIONALE_WORDS = 4
JUDGE_RATIONALE_MAX_WORDS = 25
JUDGE_CALIBRATION_TOLERANCE = 1
JUDGE_DEFAULT_TIMEOUT_S = 120.0
JUDGE_CHAT_PATH = "/chat/completions"

# ---------------------------------------------------------------------------
# Gate J2 (rubric §12.7 ruling, 2026-10-26)
# ---------------------------------------------------------------------------
# J2 replaces the §8.5 "any cell within +/-1" gate, which rejected on a
# 3-answer sample and had no signed-bias term. The constants are the ruling's,
# not tuning knobs: changing one changes the certification.
JUDGE_GATE = "J2"
JUDGE_GATE_A_WEIGHT = 0.20  # dimensions at or above this weight must be +/-1
JUDGE_GATE_T_MAX = 1  # at most one |e| >= 2 pair ...
JUDGE_GATE_T_WEIGHT = 0.15  # ... and only at or below this weight
JUDGE_GATE_B_MAX = 0.25  # signed bias of the weighted mean, per answer
JUDGE_GATE_S_MIN = 3  # cal-05 minus cal-01 must be >= 3 on this many dimensions
JUDGE_GATE_S_SPAN = 3
JUDGE_GATE_U_MAX = 1  # at most one dimension with range >= 2 ...
JUDGE_GATE_U_WEIGHT = 0.20  # ... and only strictly below this weight
# Provisional certification: if the §8.4 unstable-cell rate on the scored set
# exceeds this, the report withholds the judged half instead of publishing J.
JUDGE_GATE_MAX_UNSTABLE_RATE = 0.15
# Calibration takes the three base calls and keeps taking one extra call while
# a dimension is still unstable, up to this many extras (5 calls in total).
JUDGE_CALIBRATION_EXTRA_CALLS = 2

# ---------------------------------------------------------------------------
# Judge transport pacing and rate-limit retry
# ---------------------------------------------------------------------------
# Albert enforces 10 requests/minute on this endpoint (a 429 body says so).
# 6.5 s leaves headroom for a retried call without spending the pass in 429s.
JUDGE_MIN_INTERVAL_S = 6.5
# Same retry shape as the capture adapter: 429/5xx/timeouts, full jitter,
# Retry-After honoured. The judge is slow and expensive, so it gets more tries.
JUDGE_RETRY_MAX_ATTEMPTS = 4
JUDGE_RETRY_BASE_DELAY_S = 5.0
JUDGE_RETRY_MAX_DELAY_S = 60.0

# ---------------------------------------------------------------------------
# opencode CLI adapter
# ---------------------------------------------------------------------------
OPENCODE_BIN_ENV = "BENCH_OPENCODE_BIN"
OPENCODE_BIN_DEFAULT = "opencode"
OPENCODE_AGENT_NAME = "coach-bench"
OPENCODE_AGENT_STEPS = 1
OPENCODE_CONFIG_FILENAME = "opencode.jsonc"
OPENCODE_CONFIG_SCHEMA = "https://opencode.ai/config.json"
# Deny-all: the benchmark measures the coach prompt, never the coding agent.
OPENCODE_DENY_ALL = ({"action": "*", "resource": "*", "effect": "deny"},)

# Hosts that do not need an API key (Ollama, LM Studio, a local gateway).
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------
REDACTION_PLACEHOLDER = "[REDACTED]"

# The OpenAI-compatible chat path used when a roster line supplies its own
# base URL (the app registry supplies the path for registry models).
PRODUCTION_CHAT_PATH = "/chat/completions"

# ---------------------------------------------------------------------------
# Retry policy (HTTP adapter only; the runner stays transport-agnostic)
# ---------------------------------------------------------------------------
# A 429, a 5xx or a timeout is worth another attempt; a 401/403/404 and an
# empty or thinking-only answer are not. Delays use full-jitter exponential
# backoff unless the provider sends Retry-After, which wins.
RETRY_MAX_ATTEMPTS = 5
RETRY_BASE_DELAY_S = 2.0
RETRY_MAX_DELAY_S = 60.0
# The per-attempt HTTP timeout never drops below this, even after a long
# pacing wait has eaten the remaining budget. The attempt still counts against
# the total budget; this only avoids a zero-second socket timeout.
RETRY_MIN_ATTEMPT_TIMEOUT_S = 5.0

# ---------------------------------------------------------------------------
# Per-model pacing
# ---------------------------------------------------------------------------
# Minimum interval between request starts to the same origin/model. The
# default is 0: no pacing unless the provider publishes a budget and has been
# observed to enforce it.
#
# Albert (the endpoint that returned the 2026-10 capture's 429s) allows 128k
# input tokens per minute and 50 requests per minute. A frozen snapshot plus
# the system prompt and tool schemas is ~7.5k input tokens, so tokens bind
# first: 128000 / 7500 = ~17 calls/min, i.e. 3.52 s. Rounded up to 3.75 s
# (~16 calls/min) to leave headroom for a larger snapshot.
PACING_DEFAULT_INTERVAL_S = 0.0
PACING_INTERVALS: dict[str, float] = {"qwen3-coder-30b": 3.75}
PACING_SNAPSHOT_TOKENS = 7_500
# Published limits, used by the dry run to show why an interval was chosen and
# how many calls per minute it allows.
PACING_BUDGETS: dict[str, dict[str, float]] = {
    "qwen3-coder-30b": {"input_tokens_per_min": 128_000, "requests_per_min": 50},
}
