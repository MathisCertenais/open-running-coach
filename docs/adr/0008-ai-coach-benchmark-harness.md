# Benchmark the shipped coach, not a copy of it

Model choice for the AI coach is currently an opinion. A dev-only harness under
`bench/` asks the five canonical coach prompts (`COACH_SUGGESTIONS`,
`app/static/app.js:1411`) of every accessible model, against frozen synthetic
athlete snapshots, stores the raw answers, scores them with an ordered rubric and
writes a Markdown/JSON report that answers "which accessible model is the best
running coach here?".

The harness is standard-library only, invoked by hand (`python -m bench.cli`),
never imported by `app/`, and never run by pytest or CI. Its unit tests drive a
fake provider and make no network calls.

Two things make the result trustworthy:

1. **It runs the production path.** `bench` calls the same `run_chat()` that
   `chat()` wraps — same system prompt, same `build_messages()` serialisation,
   same tool loop, same per-model request settings, same retry-without-tools
   fallback — instead of reimplementing any of it. This needs one production
   refactor: the body of `chat()` (`app/coach_llm.py:458`) moves into
   `run_chat(...) -> ChatTrace` and `chat()` becomes a thin wrapper that
   returns `.text`. Callers do not change.
2. **Capture, scoring and reporting are separate passes** over an append-only
   JSONL file. An answer is paid for once; a rubric change is rescored offline;
   a crashed sweep resumes where it stopped.

## Why

A benchmark that reimplements the prompt or the loop measures the re-write, and
the re-write will drift within a month — the tool-budget nudge at
`app/coach_llm.py:534` and the `HTTP 400` tools fallback at
`app/coach_llm.py:491` are exactly the behaviours a copy would forget. The cost
of not duplicating is ~25 lines moved inside one module plus a `ChatTrace`
dataclass that production discards.

Comparing models over months needs the inputs to be frozen: a real athlete's
snapshot changes every week, so the same prompt would be testing the data as
much as the model. Hence synthetic snapshots, committed as JSON, with a version
and a hash that both the sweep id and the report carry.

"Best coach" must be explainable. A single opaque score lets a model win on
verbosity, and a refusal to advise a runner in pain should never be averaged away
against a well-formatted answer. Criteria are scored separately, safety is a
gate rather than a weight, and the report states which criteria separated the
models and which did not.

## Consequences

- `app/coach_llm.py` gains `run_chat()` and `ChatTrace`; `chat()` keeps its
  signature and returns the same string. `tests/test_coach_loop.py` moves its
  fake from `_request` to the new transport seam (ten tests, mechanical).
- `bench/` reads production constants from `app/config.py`
  (`LLM_MAX_TOKENS`, `LLM_TEMPERATURE`, `LLM_MAX_TOOL_ROUNDS`,
  `LLM_CONTEXT_MAX_CHARS`) and never redefines them. Benchmark-only settings —
  repeats, thresholds, paths, prices — live in `bench/config.py`, because they
  change how a measurement is taken, not how the product behaves, and because
  `app/config.py` ships inside the packaged app.
- `coach_tools` takes its notion of "today" from the tool context when present
  (`bench` pins it to the snapshot's date, production keeps `date.today()`).
  This keeps a frozen fixture meaningful months later and makes the tool
  handlers clock-free, which the pure-function rule already asks for.
- Fixtures are frozen artefacts, not generated on every run. Regenerating one
  produces a new version and a new sweep id; old sweeps stay comparable with
  each other and never with the new one.
- The report distinguishes fidelity: OpenAI-compatible HTTP runs use the
  production system prompt and tools; runs through the vendor CLI adapter are a
  **proxy**, because the CLI can only receive the system prompt through an agent
  `system` field (still preceded by project instructions), cannot set
  temperature or `maxTokens` in V2 agent config, and cannot call this app's
  Python tools. Proxy and production numbers are reported side by side, never
  silently pooled into one ranking.
- Subprocess and HTTP costs are real money. `bench capture --dry-run` prints the
  planned call count and estimated cost before anything is spent.
- Criteria, severities, the `R / Gate / Coverage / Composite` formulas and the
  rule for declaring one model better than another live in
  `docs/ai-benchmark-rubric.md`. The harness implements them and does not
  restate them; a rubric change is rescored offline without new answers.
- `bench/data/` is gitignored: it contains model output describing a synthetic
  athlete, but the directory is a scratch space and must not become a second
  source of truth.
- `CODING_STANDARDS.md` needs one line saying dev tooling under `bench/` keeps
  its own config module, so the "new tunable values live in `app/config.py`"
  check does not block every harness diff.

## Rejected alternatives

- **An in-app benchmark page.** It would put model evaluation, provider keys and
  a multi-minute sweep inside the product the benchmark is meant to judge, add a
  runtime surface for a task performed twice a year, and violate the local-first
  rule the moment a sweep calls six remote providers from the app process.
- **LLM-judge only.** Cheap to build, but it cannot verify the one thing that
  matters most — whether a number in the answer exists in the snapshot — and it
  replaces a reproducible result with an opinion about an opinion. The judge is
  kept as an optional second stage for criteria a checker cannot express.
- **pytest-mocked-only.** Unit tests with a fake provider prove the harness
  works; they cannot tell you which model is the better coach. The sweep must
  run against real providers, manually, outside CI.
- **One bespoke script per provider.** Three scripts, three record shapes, three
  reports, and no way to add a new endpoint the day its key arrives. The
  provider protocol exists so a new endpoint is a roster line, not a code path.
- **Storing runs in SQLite.** It would put benchmark data in `coach.db`, next to
  the athlete's health data, and make a sweep file impossible to copy, diff or
  review. JSONL is the smaller surface.
