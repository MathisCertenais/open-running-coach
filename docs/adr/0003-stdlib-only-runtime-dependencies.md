# Standard library only, beyond FastAPI and Uvicorn

The runtime dependency set is `fastapi` and `uvicorn`, plus what FastAPI already
pulls in. Everything else — KMZ/GPX/TCX parsing, statistics, smoothing,
training-load analytics, SQLite access, HTTP for the LLM client, the file
connectors — is written against the standard library.

## Why

The install must stay trivial on a laptop with no toolchain, and the code must
remain auditable: every number the app shows an athlete about their body comes
from code in this repository, not from a transitive dependency nobody read. Two
dependencies also means two things to keep patched in a project with no
maintainer team.

## Consequences

- XML parsing uses `xml.etree.ElementTree`; KMZ uses `zipfile`.
- No NumPy or pandas, so numerical code is explicit Python loops. Optimise only
  where a real file makes it slow.
- No `requests`; the LLM client uses `urllib.request`.
- Dev-only tooling (`pytest`, `ruff`) is allowed, lives in
  `requirements-dev.txt`, and must never be imported by `app/`.
- A pull request adding a runtime dependency needs an ADR superseding this one.
