"""The capture plan: deterministic ids and the hash that defines comparability.

Two sweeps are comparable exactly when their ``plan_hash`` matches. The hash
covers everything that changes an answer: model request settings, fixture
hashes, prompt hashes, repeat count and the rubric/judge identity.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

from . import config
from .providers.base import ModelSpec


@dataclass(frozen=True)
class Prompt:
    """One frozen canonical prompt."""

    id: str
    text: str
    sha256: str


@dataclass(frozen=True)
class FixtureRef:
    """Identity of one frozen fixture, without its payload."""

    scenario: str
    version: int
    snapshot_sha256: str
    tool_context_sha256: str


@dataclass(frozen=True)
class Fixture:
    """A frozen fixture loaded for capture."""

    scenario: str
    version: int
    as_of: str
    snapshot: Mapping[str, object]
    tool_context: Mapping[str, object]
    snapshot_sha256: str
    tool_context_sha256: str

    def ref(self) -> FixtureRef:
        """Identity-only view used by the plan and its hash."""
        return FixtureRef(
            scenario=self.scenario,
            version=self.version,
            snapshot_sha256=self.snapshot_sha256,
            tool_context_sha256=self.tool_context_sha256,
        )


@dataclass(frozen=True)
class WorkItem:
    """One (model, fixture, prompt, repeat) cell of a sweep."""

    id: str
    model: ModelSpec
    fixture: FixtureRef
    prompt: Prompt
    repeat: int


@dataclass(frozen=True)
class BenchmarkPlan:
    """The ordered work list plus the inputs that made it comparable."""

    plan_hash: str
    seed: int
    repeats: int
    models: tuple[ModelSpec, ...]
    fixtures: tuple[FixtureRef, ...]
    prompts: tuple[Prompt, ...]
    items: tuple[WorkItem, ...]
    rubric_hash: Optional[str]
    judge_model: Optional[str]
    system_prompt_sha256: str

    def as_dict(self) -> dict:
        """Serialise everything the report needs to identify this plan."""
        return {
            "plan_hash": self.plan_hash,
            "seed": self.seed,
            "repeats": self.repeats,
            "models": [model.signature() for model in self.models],
            "fixtures": [
                {
                    "scenario": fixture.scenario,
                    "version": fixture.version,
                    "snapshot_sha256": fixture.snapshot_sha256,
                    "tool_context_sha256": fixture.tool_context_sha256,
                }
                for fixture in self.fixtures
            ],
            "prompts": [
                {"id": prompt.id, "sha256": prompt.sha256} for prompt in self.prompts
            ],
            "rubric_hash": self.rubric_hash,
            "judge_model": self.judge_model,
            "system_prompt_sha256": self.system_prompt_sha256,
        }


def canonical_json(payload: object) -> str:
    """Stable JSON used for every hash in the harness."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def sha256_text(text: str) -> str:
    """SHA-256 of UTF-8 text, lowercase hex."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_payload(payload: object) -> str:
    """SHA-256 of the canonical JSON encoding of a payload."""
    return sha256_text(canonical_json(payload))


def _as_models(models: object) -> list[ModelSpec]:
    specs = getattr(models, "specs", models)
    return list(specs)


def _as_fixture_ref(fixture: object) -> FixtureRef:
    if isinstance(fixture, FixtureRef):
        return fixture
    ref = getattr(fixture, "ref", None)
    if callable(ref):
        return ref()
    if isinstance(fixture, Mapping):
        return FixtureRef(**fixture)
    raise TypeError(f"not a fixture reference: {fixture!r}")


def _as_prompt(prompt: object) -> Prompt:
    if isinstance(prompt, Prompt):
        return prompt
    if isinstance(prompt, Mapping):
        text = str(prompt["text"])
        return Prompt(
            id=str(prompt["id"]),
            text=text,
            sha256=str(prompt.get("sha256") or sha256_text(text)),
        )
    raise TypeError(f"not a prompt: {prompt!r}")


def record_id(
    plan_hash: str, model_key: str, scenario: str, prompt_id: str, repeat: int
) -> str:
    """Deterministic id, so resume matches by identity not by position."""
    raw = "|".join((plan_hash, model_key, scenario, prompt_id, str(repeat)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[: config.RECORD_ID_CHARS]


def compute_plan_hash(
    models: Sequence[ModelSpec],
    fixtures: Sequence[FixtureRef],
    prompts: Sequence[Prompt],
    repeats: int,
    seed: int,
    *,
    rubric_hash: Optional[str] = None,
    judge_model: Optional[str] = None,
    system_prompt_sha256: str = "",
) -> str:
    """Hash every input that can change an answer or its comparability."""
    model_list = _as_models(models)
    fixture_list = [_as_fixture_ref(fixture) for fixture in fixtures]
    prompt_list = [_as_prompt(prompt) for prompt in prompts]
    payload = {
        "schema_version": config.BENCH_SCHEMA_VERSION,
        "models": [model.signature() for model in model_list],
        "fixtures": [
            {
                "scenario": fixture.scenario,
                "version": fixture.version,
                "snapshot_sha256": fixture.snapshot_sha256,
                "tool_context_sha256": fixture.tool_context_sha256,
            }
            for fixture in fixture_list
        ],
        "prompts": [
            {"id": prompt.id, "sha256": prompt.sha256} for prompt in prompt_list
        ],
        "repeats": repeats,
        "seed": seed,
        "rubric_hash": rubric_hash,
        "judge_model": judge_model,
        "system_prompt_sha256": system_prompt_sha256,
    }
    return sha256_payload(payload)


def build_plan(
    models: Sequence[ModelSpec],
    fixtures: Sequence[FixtureRef],
    prompts: Sequence[Prompt],
    repeats: int,
    seed: int,
    *,
    rubric_hash: Optional[str] = None,
    judge_model: Optional[str] = None,
    system_prompt_sha256: str = "",
) -> BenchmarkPlan:
    """Build the ordered work list: model, then repeat, then fixture, prompt.

    Repeats are spread across time on purpose: running all three repeats of a
    prompt back-to-back lets provider-side caching flatter one model.
    """
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    model_list = _as_models(models)
    fixture_refs = [_as_fixture_ref(fixture) for fixture in fixtures]
    prompt_list = [_as_prompt(prompt) for prompt in prompts]
    if not model_list or not fixture_refs or not prompt_list:
        raise ValueError("a plan needs at least one model, fixture and prompt")

    plan_hash = compute_plan_hash(
        model_list,
        fixture_refs,
        prompt_list,
        repeats,
        seed,
        rubric_hash=rubric_hash,
        judge_model=judge_model,
        system_prompt_sha256=system_prompt_sha256,
    )
    items: list[WorkItem] = []
    for model in model_list:
        for repeat in range(repeats):
            for fixture in fixture_refs:
                for prompt in prompt_list:
                    items.append(
                        WorkItem(
                            id=record_id(
                                plan_hash,
                                model.key,
                                fixture.scenario,
                                prompt.id,
                                repeat,
                            ),
                            model=model,
                            fixture=fixture,
                            prompt=prompt,
                            repeat=repeat,
                        )
                    )
    return BenchmarkPlan(
        plan_hash=plan_hash,
        seed=seed,
        repeats=repeats,
        models=tuple(model_list),
        fixtures=tuple(fixture_refs),
        prompts=tuple(prompt_list),
        items=tuple(items),
        rubric_hash=rubric_hash,
        judge_model=judge_model,
        system_prompt_sha256=system_prompt_sha256,
    )


def sweep_dir(root: Path, slug: str) -> Path:
    """Directory for one named sweep under ``root``."""
    return root / config.SWEEPS_DIRNAME / slug
