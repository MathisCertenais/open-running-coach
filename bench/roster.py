"""Read the roster and resolve each line into a callable ``ModelSpec``.

Availability is environment state, not plan state: a missing key must produce
an ``Availability`` entry, never an exception and never a different plan hash.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

from app import coach_llm, coach_tools

from . import config
from .providers import ADAPTERS
from .providers.base import Availability, AvailabilityStatus, ModelSpec, Pricing


@dataclass(frozen=True)
class Roster:
    """The parsed roster plus the env names whose values must be redacted."""

    specs: tuple[ModelSpec, ...]
    prices_as_of: str
    secret_env_names: tuple[str, ...]
    path: Path

    def by_key(self) -> dict[str, ModelSpec]:
        """Index the roster by its stable benchmark key."""
        return {spec.key: spec for spec in self.specs}


def _tool_count(setting: object) -> int:
    if setting is False:
        return 0
    if isinstance(setting, int) and not isinstance(setting, bool):
        return min(max(0, setting), len(coach_tools.TOOL_SCHEMAS))
    return len(coach_tools.TOOL_SCHEMAS)


def _production_params(registry_id: str, timeout_s: float) -> dict:
    model = coach_llm.find_model(registry_id)
    if model is None:
        return {"timeout_s": timeout_s}
    return {
        "temperature": model["temperature"],
        "max_tokens": model["max_tokens"],
        "tools": _tool_count(model.get("tools", True)),
        "timeout_s": timeout_s,
        "timeout_overridden": timeout_s != config.DEFAULT_TIMEOUT_S,
    }


def _proxy_params(timeout_s: float) -> dict:
    return {
        "temperature": "provider_default",
        "max_tokens": None,
        "tools": 0,
        "timeout_s": timeout_s,
        "timeout_overridden": timeout_s != config.DEFAULT_TIMEOUT_S,
    }


def _pricing(raw: object) -> Optional[Pricing]:
    if not isinstance(raw, dict):
        return None
    try:
        return Pricing(
            input_per_mtok=float(raw["input_per_mtok"]),
            output_per_mtok=float(raw["output_per_mtok"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid pricing block: {raw!r}") from exc


def _spec(entry: dict, timeout_s: float) -> ModelSpec:
    adapter = str(entry.get("adapter") or "")
    if adapter not in ADAPTERS:
        raise ValueError(f"unknown adapter {adapter!r} for {entry.get('key')!r}")
    if not entry.get("key") or not entry.get("origin") or not entry.get("model"):
        raise ValueError(f"roster entry needs key, origin and model: {entry!r}")

    registry_id = entry.get("registry_id")
    if adapter == "openai_http":
        params = _production_params(str(registry_id or ""), timeout_s)
    elif adapter == "opencode_cli":
        params = _proxy_params(timeout_s)
    else:
        params = dict(entry.get("params") or {})
        params.setdefault("timeout_s", timeout_s)

    cohort = entry.get("cohort") or (
        "production" if adapter == "openai_http" else "proxy"
    )
    if cohort not in ("production", "proxy"):
        raise ValueError(f"unknown cohort {cohort!r} for {entry.get('key')!r}")
    return ModelSpec(
        key=str(entry["key"]),
        adapter=adapter,
        origin=str(entry["origin"]),
        model=str(entry["model"]),
        cohort=cohort,
        variant=entry.get("variant"),
        registry_id=str(registry_id) if registry_id else None,
        pricing=_pricing(entry.get("pricing")),
        params=params,
        enabled=bool(entry.get("enabled", True)),
        label=entry.get("label"),
        disabled_reason=entry.get("disabled_reason"),
    )


def load_roster(path: Path | None = None, *, timeout_s: float | None = None) -> Roster:
    """Read ``models.json`` and resolve every entry.

    An unknown registry id is kept: availability reports it later, which is what
    lets the CLI say "3 of 5 models available (albert: missing key)".
    """
    source = path or config.ROSTER_FILE
    document = json.loads(source.read_text(encoding="utf-8"))
    rows = document.get("models")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{source} has no models")
    timeout = timeout_s if timeout_s is not None else config.DEFAULT_TIMEOUT_S
    specs = tuple(_spec(row, timeout) for row in rows)
    keys = [spec.key for spec in specs]
    if len(set(keys)) != len(keys):
        raise ValueError("roster keys must be unique")
    secret_names = tuple(
        sorted({str(row["api_key_env"]) for row in rows if row.get("api_key_env")})
    )
    return Roster(
        specs=specs,
        prices_as_of=str(document.get("prices_as_of") or ""),
        secret_env_names=secret_names,
        path=source,
    )


def select_specs(roster: Roster, names: Sequence[str] | None) -> list[ModelSpec]:
    """Resolve ``all`` or a comma-separated list of roster keys."""
    if not names or list(names) == ["all"]:
        return list(roster.specs)
    wanted: list[str] = []
    for name in names:
        wanted.extend(part.strip() for part in name.split(",") if part.strip())
    by_key = roster.by_key()
    unknown = [name for name in wanted if name not in by_key]
    if unknown:
        raise ValueError(
            f"unknown model(s): {', '.join(unknown)}. Known: {', '.join(by_key)}"
        )
    return [by_key[name] for name in wanted]


def availability_for(spec: ModelSpec) -> Availability:
    """Ask the adapter whether this roster line can run here."""
    provider = ADAPTERS.get(spec.adapter)
    if provider is None:
        return Availability(
            AvailabilityStatus.UNKNOWN_ID, f"no adapter {spec.adapter!r}"
        )
    return provider.availability(spec)


def availability_map(
    specs: Iterable[ModelSpec],
) -> dict[str, Availability]:
    return {spec.key: availability_for(spec) for spec in specs}
