"""Dev-time fixture generator.

Run this once to freeze a fixture version, review the diff, and commit it. A
regeneration is a new version because ``build_snapshot`` bakes the generation
day into the athlete's windows: ``v1`` and ``v2`` answers are never merged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

from .. import config
from ..plan import sha256_payload
from . import scenarios


def _generator_sha256() -> str:
    """Hash the athlete definition, which is what determines the fixtures.

    The writer is not hashed: editing its output formatting must not look like
    a fixture change. A change to ``scenarios.py`` is a version bump.
    """
    return hashlib.sha256(Path(scenarios.__file__).read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def freeze(
    as_of: date | None = None,
    version: int | None = None,
    *,
    force: bool = False,
) -> list[Path]:
    """Build and write every scenario, refusing to overwrite a frozen version."""
    as_of = as_of or date.today()
    version = version if version is not None else config.FIXTURE_VERSION
    targets = [
        config.SNAPSHOTS_DIR / f"{name}.v{version}.json" for name in scenarios.SCENARIOS
    ] + [
        config.TOOL_CONTEXT_DIR / f"{name}.v{version}.json"
        for name in scenarios.SCENARIOS
    ]
    existing = [path for path in targets if path.exists()]
    if existing and not force:
        raise SystemExit(
            "Refusing to overwrite frozen fixtures "
            f"({', '.join(f'{path.parent.name}/{path.name}' for path in existing)}). "
            "Freeze a new --version instead."
        )

    generator = _generator_sha256()
    generated_at = _now()
    written: list[Path] = []
    for name in scenarios.SCENARIOS:
        data = scenarios.build(name, as_of)
        snapshot = scenarios.build_snapshot(data)
        tool_payload = scenarios.serialize_tool_context(data)
        failures = scenarios.check_expectations(
            name, snapshot, scenarios.deserialize_tool_context(tool_payload)
        )
        if failures:
            raise SystemExit(
                f"{name} does not satisfy its expectations:\n- " + "\n- ".join(failures)
            )

        snapshot_sha = sha256_payload(snapshot)
        tool_sha = sha256_payload(tool_payload)
        meta = {
            "scenario": name,
            "version": version,
            "as_of": as_of.isoformat(),
            "generated_at": generated_at,
            "generator_sha256": generator,
        }
        snapshot_path = config.SNAPSHOTS_DIR / f"{name}.v{version}.json"
        tool_path = config.TOOL_CONTEXT_DIR / f"{name}.v{version}.json"
        _write(
            snapshot_path,
            {
                "meta": {
                    **meta,
                    "snapshot_sha256": snapshot_sha,
                    "tool_context_sha256": tool_sha,
                },
                "snapshot": snapshot,
            },
        )
        _write(
            tool_path,
            {
                "meta": {
                    **meta,
                    "tool_context_sha256": tool_sha,
                    "snapshot_sha256": snapshot_sha,
                },
                "tool_context": tool_payload,
            },
        )
        written.extend((snapshot_path, tool_path))
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=None,
        help="Freeze date (YYYY-MM-DD); defaults to today.",
    )
    parser.add_argument(
        "--version",
        type=int,
        default=config.FIXTURE_VERSION,
        help="Fixture version to write.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the version (normally a version bump is required).",
    )
    args = parser.parse_args(argv)
    try:
        written = freeze(args.as_of, args.version, force=args.force)
    except SystemExit as exc:
        print(exc)
        return 1
    for path in written:
        print(path.relative_to(config.REPO_ROOT))
    return 0


if __name__ == "__main__":  # pragma: no cover - dev entry point
    raise SystemExit(main())
