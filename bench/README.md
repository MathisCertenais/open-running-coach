# AI coach benchmark harness

Dev-only. It answers one question: **which accessible chat model is the best
running coach in this application?** It asks the five prompts the coach panel
already offers (`COACH_SUGGESTIONS` in `app/static/app.js`) of every candidate
model, against frozen synthetic athlete snapshots, and stores every answer so a
versioned rubric can score it later.

The authority split is deliberate:

- `docs/ai-benchmark-spec.md` — what is captured, how, and the record schema.
- `docs/ai-benchmark-rubric.md` — what is scored and how.
- `docs/adr/0008-ai-coach-benchmark-harness.md` — why the harness calls
  production code instead of a copy.

Nothing here runs in the app, in CI or in pytest. `app/` never imports `bench/`;
a test pins that direction.

## What is implemented

| Phase | Status |
| --- | --- |
| 0 — production seam (`run_chat`, `ChatTrace`, pinned tool clock) | done |
| 1 — scenarios, frozen `v1` fixtures, prompt fixture | done |
| 2 — roster, plan, runner, providers, `capture` | done |
| 3 — checks, rubric, aggregation | done (`bench/scoring/`) |
| 4 — report | done (`bench/report.py`, `report`) |
| 5 — optional LLM judge | done (`bench/scoring/judge.py`, `score --judge`) |

`capture` is the only command that calls a model under test. `fixtures`,
`providers`, `capture --dry-run` and `report` make no model calls. `score`
without `--judge` is offline; `score --judge` calls the judge only.

## Run

```bash
# Verify the committed fixtures and prompt set.
python -m bench.cli fixtures --check

# Show which roster models have credentials/binaries here.
python -m bench.cli providers

# What would this cost, without calling anything?
python -m bench.cli capture --models all --repeats 3 --dry-run

# Capture answers (writes bench/data/sweeps/<slug>/).
python -m bench.cli capture --models gemma-4-31b,qwen2.5-7b-instruct \
    --scenarios healthy,red_flags --repeats 3

# Score every stored answer offline; rescoring after a rubric change is free.
python -m bench.cli score bench/data/sweeps/<slug>

# Render report.md and report.json (blocker rate first, verdicts from aggregate).
python -m bench.cli report bench/data/sweeps/<slug>

# Score with the blind judge. A judge not in models.json is registered from flags:
python -m bench.cli score bench/data/sweeps/<slug> \
    --judge deepseek-v4-flash-0731 \
    --judge-base-url "<judge-endpoint>" \
    --judge-model deepseek-v4-flash-0731 \
    --judge-key-env JUDGE_API_KEY \
    --judge-repeats 0 \
    --judge-scenarios healthy,calibrating
```

`<judge-endpoint>` is the full base URL of an OpenAI-compatible judge
endpoint, version path included (for example, ending in `/v1`); take the
current value from the operator. `<slug>` is the sweep directory name you
choose, and the sweep commands below read it back.

`capture` records the rubric file (`--rubric`, default
`bench/fixtures/rubric.json`) and the judge model id (`--judge-model`) in
`meta.json`, and both are covered by the `plan_hash`: a sweep captured under one
rubric cannot be scored as if it were captured under another. `meta.json` keeps
the rubric text and its sha256, so an old sweep stays auditable after the file
moves.

`capture --force` **replaces** a sweep; it never appends to it. When the
directory already holds records from a different `plan_hash`, the old
`records.jsonl` is moved to `records.<old plan_hash>.jsonl.bak` and the new
stream starts empty. Scoring and reporting only ever read `records.jsonl`, so
two plans are never read together and the `--force` overwrite is visible on disk
rather than silent.

`score` refuses to start when `records.jsonl` mixes plan hashes, when `meta.json`
names a different plan hash, or when the rubric/judge differs from the one the
plan was captured with. `--allow-stale` scores anyway and prints a warning;
`report` then refuses the result unless it is also given `--allow-stale`, which
prints a prominent staleness banner above the header. Rescoring is cheap, so
refusing is the default.

`score` reads `records.jsonl`, applies `bench/fixtures/rubric.json` and rewrites
`scores.jsonl` atomically. It never calls a provider: the same records always
produce byte-identical scores, which is what makes an old sweep auditable. A
rule in the rubric with no implementation in `bench/scoring/checks.py` is
reported as `unknown_rule` and blocks any verdict, rather than scoring zero.

`--judge-repeats N` judges repeat index `N` only, and `--judge-scenarios`
limits the judged scenarios, so a three-repeat sweep can afford one judge pass
per cell. A cell that is not judged is stored as `judge_missing` and counted;
it is never imputed into the mean, which is computed over judged PASS answers
only (rubric §9.2).

Keys come from the environment only. Each roster line names `api_key_env`
(for example `GEMMA_API_KEY`); the roster never stores a key. A model without a
key is reported as `missing_key` in `meta.json` and skipped — it is not an
error and it does not abort the sweep. `score` also redacts the judge key
(`--judge-key-env`) out of every judge detail before writing `scores.jsonl` or
`meta.json`.

`report` reads `meta.json`, `records.jsonl` and `scores.jsonl` and writes
`report.md`/`report.json` in spec §8 order. It takes the verdict from
`aggregate()`, prints the blocker rate before any composite, states every
model's cohort, and never compares cohorts. The same inputs produce
byte-identical files: a report contains no wall clock.

The judge (rubric §8, §12.5) scores usability only, blind to model identity,
the scenario label and every deterministic outcome. It runs three calls per
answer (median), a fourth when a dimension spans two or more points, and marks
an unstable cell `judge-unstable` rather than imputing it. Invalid JSON, prose
around the JSON, a reasoning-only reply and a contract violation each get one
retry; then the cell is `judge-invalid` with no imputed score.

Certification is **Gate J2** (rubric §12.7), a documented relaxation of §8.5:
the six conditions (V, A, T, B, S, U) bound the signed bias of the published J
instead of rejecting on any single calibration cell. The calibration runs the
three hand-scored answers in `bench/fixtures/judge_calibration.v1.json`; the
result and the per-dimension medians/errors are recorded in that file's
`calibration_runs` metadata and in `meta.json`. A judge that is a model under
test is refused. J is provisional: if the §8.4 unstable-cell rate on the scored
set exceeds 15%, the report withholds J and issues no verdict. No composite is
published.

The judge transport paces itself at `JUDGE_MIN_INTERVAL_S` (6.5 s, because the
endpoint allows 10 requests/minute) and retries 429/5xx/timeouts with the same
full-jitter/Retry-After policy as the capture adapter.

`bench/data/` is gitignored. Append-only `records.jsonl` is the index; a
crashed sweep resumes from it by `record_id`, not by position. Reusing a sweep
slug with a different `plan_hash` is refused unless `--force` is given, and
`--force` replaces the sweep by archiving the old `records.jsonl`; the two plans
are never scored together.

## Fixtures

Fixtures are frozen artefacts, not rebuilt per run. `build_snapshot()` bakes the
generation day into the athlete's windows, so a rebuild shifts the input and
invalidates months of stored answers.

```bash
python -m bench.fixtures.build_fixtures --version 2   # a version bump, not an edit
```

`bench/fixtures/scenarios.py` declares `EXPECTATIONS` for each scenario. The
builder refuses to write a fixture that does not satisfy them, and
`tests/test_bench_fixtures.py` re-asserts them on the committed files. The
`red_flags` scenario keeps a sharp load increase and an active pain episode
precisely because the safety checks would otherwise be vacuous.

`bench/fixtures/prompts.json` is a frozen copy of `COACH_SUGGESTIONS`; a guard
test parses `app.js` and fails when the two diverge.

## Cohorts and fidelity

Every roster entry carries a cohort:

- `production` — `openai_http`; the same `run_chat()` the app calls, same system
  prompt, same tools, same temperature and `max_tokens`.
- `proxy` — the vendor CLI adapter; the prompt goes through the CLI's agent
  wrapper.

Proxy and production numbers are never ranked together. Records carry both
`model.cohort` and `model.fidelity` so the scoring phase can keep them apart.

## The vendor CLI adapter

**Disabled in `models.json` after the pilot.** The CLI injects its own agent
context around the request; one captured answer read *"I did not make any tool
calls... must be some kind of injection"*, so the CLI path measures the model
plus a wrapper, not the model. An OpenAI-compatible endpoint for the same model
family is the supported route: add it as an `openai_http` roster line (spec
§3.1). The adapter remains for the `--control` idea in spec §7.5, and a failed
call always keeps its raw event stream.

Verified on the pilot's CLI build, with the CLI's own `--help` output and the
published config schema:

- The CLI runs non-interactively, once per record, with JSON event output, a
  named agent that carries the coach system prompt, a
  `provider/model[#variant]` selector, and the athlete data plus the prompt as
  the single message argument.
- The V2 config key is `agents`; an entry accepts `system`, `steps`, `mode` and
  a `permissions` ruleset. The generated config file sets `steps: 1` and
  deny-all permissions, and writes `coach_llm.SYSTEM_PROMPT` at run time so it
  cannot drift from the product. It is passed to the CLI as an explicit config
  path and the cwd stays otherwise empty: cwd-based discovery from a system
  temp directory did not resolve the agent reliably on macOS, even though the
  CLI's own config diagnostic listed the file.
- `--format json` emits one JSON object per line. Observed event types:
  `step_start`, `text`, `error`; the SDK also declares `step-finish` parts with
  `reason`, `cost` and `tokens`. A local model run emitted no `step-finish`, so
  usage is reported as unknown rather than invented.
- The CLI cannot set this app's temperature or `max_tokens` and cannot call its
  Python tools. The cwd is a throwaway directory, but instructions from a
  global CLI config directory may still be prepended, and a `steps: 1` run can
  append the CLI's own turn-summary text; those are recorded as
  `possible_global_instructions` and `possible_wrapper_text` and are declared
  limitations.

## Retries and pacing

The HTTP adapter retries `429`, `5xx` and timeouts; it does **not** retry
`401/403/404` or an empty/thinking-only answer. Delays are full-jitter
exponential backoff (`RETRY_BASE_DELAY_S` 2 s, capped at `RETRY_MAX_DELAY_S`
60 s) and a provider's `Retry-After` header wins over the jitter, whether it is
delta-seconds or an HTTP-date. `RETRY_MAX_ATTEMPTS` in `bench/config.py` sets
the cap. The timeout budget belongs to the whole record: each attempt gets what
is left, so a retry never restarts the clock.

`PACING_INTERVALS` adds a minimum interval between request starts to the same
origin/model. The busiest endpoint publishes 128k input tokens/min and 50
req/min; a frozen snapshot is ~7.5k input tokens, so tokens bind first and
3.75 s (~16 calls/min) keeps it under the limit. Models without a configured
interval are unpaced.
`capture --dry-run` prints the interval, the budget behind it and the pacing
floor of the estimated wall clock.

A record stores `attempts`, `retried`, `retry_reasons` (for example `["429"]`),
`retry_wait_ms` and `rate_limit_wait_ms`. A call that succeeded on its third
attempt is `status: "ok"` with `attempts: 3`, and its `latency_ms` includes the
waits. The capture summary prints retries per model and the total time spent
waiting on rate limits, and `meta.json` keeps the same counts.

## What it does not measure

- A real athlete. The snapshots are synthetic.
- A specific device or watch. GPS noise and missing heart rate are fixture
  properties, not model behaviour.
- The app UI, prompt tuning or multi-turn conversations: one prompt, one turn,
  no history.
- Anything about cost or latency as a quality signal. They are recorded, never
  used to break a tie.

## Tests

```bash
python -m pytest tests/test_bench_*.py tests/test_coach_loop.py tests/test_coach_trace.py
```

The suite uses `bench.providers.fake.FakeProvider`, a stubbed subprocess runner
and a monkeypatched `_send`; it never touches the network and never starts a
real vendor CLI process.

`tests/fixtures/safety_corpus.json` is the acceptance corpus for X-01, X-03 and
R-05: one answer, one scenario, the expected outcome per rule, including the
adversarial negations and the two deliberately ambiguous cases. Adding a safety
phrase means adding a case there, not widening a regex window.
