# Opt-in wger pull: one request per athlete action

wger stores weight, nutrition and strength training behind a documented REST API
at `/api/v2/`. The app can read it, but only when the athlete presses a button
or runs a command: `GET`-only, one bounded pull, an explicit personal API token,
and the result written as ordinary export files in `data/`.

This supersedes the closing clause of ADR-0005 ("any future feature that requires
an account or a server needs an ADR superseding this one") for this one path, and
leaves ADR-0004 as the only way rows reach SQLite.

## Why

wger is the tracker this project already recommends, and its manual export is the
single most reported friction in the import flow: the file has to be found,
exported and dropped for data that the server will hand over on request. wger is
also self-hostable and open source, so it is the one integration that does not
pull the athlete towards a proprietary cloud.

Doing it as a pull rather than a sync is what makes it compatible with the
local-first promise: the request happens on a human action, takes seconds, and
the app is offline again immediately afterwards.

## Decision

- Authentication is a personal API key, read from `WGER_TOKEN`. A permanent
  token goes out as `Authorization: Token <key>`; the 120-day JWT refresh token
  wger also offers is exchanged at `/allauth/app/v1/tokens/refresh` for a
  short-lived access token sent as `Authorization: Bearer <token>`. There is no
  OAuth client: a shipped client secret is not a secret.
- Both key kinds are supported because wger's own page mints both. Refreshing is
  necessary for the JWT: allauth's headless strategy rotates the token on every
  exchange, so the key that was just used is dead. The rotated one is written
  back to `WGER_TOKEN` in `.env` (mode 600, other lines untouched, atomic
  replace). Without that, a JWT would work exactly once — and a half-written
  `.env` would take every other key with it. The exchange is JSON because wger
  configures DRF as JSON-only; the form-encoded body in its own docs answers
  `415`.
- The pull is read-only. The client implements `GET` and nothing else; no data is
  ever written back to wger, so a mistake here cannot damage the source.
- One pull per user action, no polling, no background sync, no retry loop. The
  server watcher keeps watching `data/`, not the network.
- The payload is written to `data/nutrition/wger.json` and
  `data/workout/wger.json` and then imported by the existing connectors, so the
  result is replace-or-update, inspectable, and backed up with the rest of the
  data (ADR-0004).
- The token never leaves the server. `/api/wger/status` reports whether a key
  exists; no endpoint returns the key, writes it to the database or logs it. The
  same rule already applies to the LLM keys, so there is one policy, not two.

## Consequences

- A self-hoster points the app at their instance with `WGER_BASE_URL`; nothing
  private is hardcoded.
- Nutrition macros are recomputed locally: wger stores per-100 g ingredient
  values plus an amount and an optional weight unit, so a diary item whose
  ingredient was deleted has no trustworthy mass. Those items are skipped and
  counted in the response rather than guessed.
- wger rate-limits a few endpoints per IP. A pull is one pass of paginated
  `GET`s at `WGER_PAGE_LIMIT` per page, with `WGER_TIMEOUT_S` per request, so a
  multi-year diary is a handful of calls.
- wger's API is versioned and its OpenAPI schema is public, so a breaking change
  shows up as a `404`/`4xx` the UI reports in plain language instead of silent
  partial data.
- The app remains fully usable without a token: the panel says what is missing
  and every other import path keeps working. There is no "degraded mode".
- wger holds no GPS tracks. The API cannot replace the running file import, and
  nothing in the UI implies that it does.

## Alternatives rejected

- **OAuth application.** Needs a client secret distributed with the app and a
  redirect URI on a local port; more moving parts than a personal key, and a
  worse fit for a single-user local tool.
- **Background sync.** Breaks "works offline, forever", wakes the machine, and
  turns a one-time import into a daemon nobody asked for.
- **Writing straight into SQLite.** Skips ADR-0004's idempotency, leaves no
  artifact the athlete can inspect or back up, and makes the import
  un-reproducible once wger's data changes.
