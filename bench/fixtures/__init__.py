"""Frozen benchmark inputs: prompts, snapshots and tool contexts.

Fixtures are artefacts, not something rebuilt per run. Regenerating one is a
version bump (``v2``); results from different versions are never merged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from .. import config
from ..plan import Fixture, Prompt, sha256_payload, sha256_text
from . import scenarios


def load_prompts(path: Path | None = None) -> list[Prompt]:
    """Read the frozen copy of ``COACH_SUGGESTIONS``."""
    source = path or config.PROMPTS_FILE
    rows = json.loads(source.read_text(encoding="utf-8"))
    prompts: list[Prompt] = []
    for row in rows:
        text = row["text"]
        expected = row["sha256"]
        actual = sha256_text(text)
        if actual != expected:
            raise ValueError(
                f"prompt {row['id']!r} sha256 is {actual}, fixture says {expected}"
            )
        prompts.append(Prompt(id=row["id"], text=text, sha256=actual))
    if len({prompt.id for prompt in prompts}) != len(prompts):
        raise ValueError("prompt ids must be unique")
    return prompts


def _read_wrapper(path: Path, payload_key: str) -> tuple[dict, dict]:
    if not path.exists():
        raise FileNotFoundError(f"missing frozen fixture: {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    return document.get("meta") or {}, document[payload_key]


def load_fixture(name: str, version: int | None = None) -> Fixture:
    """Load one frozen scenario and verify its hashes before returning it."""
    version = version if version is not None else config.FIXTURE_VERSION
    snapshot_meta, snapshot = _read_wrapper(
        config.SNAPSHOTS_DIR / f"{name}.v{version}.json", "snapshot"
    )
    tool_meta, tool_payload = _read_wrapper(
        config.TOOL_CONTEXT_DIR / f"{name}.v{version}.json", "tool_context"
    )

    scenario = snapshot_meta.get("scenario") or tool_meta.get("scenario")
    if scenario != name:
        raise ValueError(f"{name}.v{version} declares scenario {scenario!r}")
    if snapshot_meta.get("version") != version:
        raise ValueError(f"{name}.v{version} declares another version")

    snapshot_sha = sha256_payload(snapshot)
    tool_sha = sha256_payload(tool_payload)
    if snapshot_meta.get("snapshot_sha256") not in (None, snapshot_sha):
        raise ValueError(f"{name}.v{version} snapshot hash does not match its meta")
    if tool_meta.get("tool_context_sha256") not in (None, tool_sha):
        raise ValueError(f"{name}.v{version} tool-context hash does not match its meta")

    return Fixture(
        scenario=name,
        version=version,
        as_of=str(tool_payload.get("today") or snapshot_meta.get("as_of")),
        snapshot=snapshot,
        tool_context=scenarios.deserialize_tool_context(tool_payload),
        snapshot_sha256=snapshot_sha,
        tool_context_sha256=tool_sha,
    )


def load_fixtures(
    names: Sequence[str] | None = None, version: int | None = None
) -> list[Fixture]:
    """Load the requested scenarios in the declared order."""
    selected = list(names or scenarios.SCENARIOS)
    for name in selected:
        if name not in scenarios.SCENARIOS:
            raise ValueError(f"Unknown scenario: {name!r}")
    return [load_fixture(name, version) for name in selected]


def verify_frozen(
    names: Sequence[str] | None = None, version: int | None = None
) -> list[str]:
    """Return every way the committed fixtures fail their declared properties."""
    failures: list[str] = []
    for fixture in load_fixtures(names, version):
        for problem in scenarios.check_expectations(
            fixture.scenario, dict(fixture.snapshot), dict(fixture.tool_context)
        ):
            failures.append(f"{fixture.scenario}.v{fixture.version}: {problem}")
    return failures
