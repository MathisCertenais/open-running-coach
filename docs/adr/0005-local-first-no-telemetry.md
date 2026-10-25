# Local-first, no telemetry, keys in environment variables

The app binds to `127.0.0.1`, stores everything in files the user owns, and makes
no outbound network request other than map tiles and the LLM coach the user has
explicitly configured. There is no analytics, no crash reporting, no licence
check and no "phone home".

## Why

The data is intimate: where a person runs, when, how fast, how their weight and
body composition change, and what they eat. Much of it
is health data. Shipping that to a server would require consent flows, retention
policies and breach liability that a single-user local app has no business
taking on. Privacy is also the product's differentiator against Strava.

## Consequences

- No usage metrics, so product decisions come from issues and conversations, not
  dashboards.
- Model API keys are read from environment variables (`.env`, gitignored) and
  are never written to `coach.db`, never logged, and never sent to the browser —
  the server proxies LLM calls.
- Map tiles are the one unavoidable external request; the tile provider receives
  the user's IP. Document it in the manual rather than pretend otherwise.
- Any future feature that requires an account or a server needs an ADR
  superseding this one.
