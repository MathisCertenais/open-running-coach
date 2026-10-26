"""Load ``rubric.json`` and apply it to one record.

The rubric document owns *what* is measured; this module owns *how* the JSON
transcription is turned into outcomes. It injects the evidence bundle, the
visible-payload view, the declared constants and the prompt text into a copy of
each rule's parameters, so a check keeps the pinned signature
``check(record, fixture, params)`` and still gets the bundle without reading
globals or another check's result.

A rule naming a check that does not exist is **not** scored as zero. It is
recorded as ``unknown_rule`` on every cell, counted, and it blocks the verdict
(spec §7.4): a rubric that grew while the code did not must make noise, not a
silent pass.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .. import config
from . import checks, grounding
from .checks import RuleOutcome, Severity

RUBRIC_FILE = config.FIXTURES_DIR / "rubric.json"


@dataclass(frozen=True)
class Rule:
    """One transcribed rubric row."""

    id: str
    severity: Severity
    check: str
    scenarios: tuple[str, ...]
    prompts: tuple[str, ...]
    params: Mapping[str, object] = field(default_factory=dict)

    def applies_to(self, scenario: str, prompt: str) -> bool:
        """True when the row's applicability covers this cell."""
        scenario_ok = "*" in self.scenarios or scenario in self.scenarios
        prompt_ok = "*" in self.prompts or prompt in self.prompts
        return scenario_ok and prompt_ok


@dataclass(frozen=True)
class Rubric:
    """The whole file: rules plus the judge block the report must disclose."""

    version: str
    source: str
    rules: tuple[Rule, ...]
    constants: tuple[float, ...]
    judge: Mapping[str, object]
    sha256: str
    unknown_rules: tuple[str, ...]
    text: str = ""
    recall: Mapping[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict:
        """Stable view for ``meta.json`` / ``report.json``."""
        return {
            "version": self.version,
            "source": self.source,
            "sha256": self.sha256,
            "rules": [
                {
                    "id": rule.id,
                    "severity": rule.severity.value,
                    "check": rule.check,
                    "scenarios": list(rule.scenarios),
                    "prompts": list(rule.prompts),
                    "params": dict(rule.params),
                }
                for rule in self.rules
            ],
            "constants": list(self.constants),
            "judge": dict(self.judge),
            "known_recall_gaps": dict(self.recall),
            "unknown_rules": list(self.unknown_rules),
        }


def _as_tuple(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ("*",)
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value)
    raise ValueError(f"{label} must be a string or a list")


_SEVERITIES = {severity.value: severity for severity in Severity}


def load_rubric(path: Path | None = None) -> Rubric:
    """Read and validate the transcription; never invent a missing rule."""
    source = path or RUBRIC_FILE
    raw = source.read_text(encoding="utf-8")
    document = json.loads(raw)
    constants = tuple(
        float(value)
        for value in document.get("constants") or ()
        if isinstance(value, (int, float))
    )

    rules: list[Rule] = []
    seen: set[str] = set()
    for row in document.get("rules") or []:
        rule_id = str(row.get("id") or "").strip()
        if not rule_id:
            raise ValueError("a rubric rule is missing its id")
        if rule_id in seen:
            raise ValueError(f"duplicate rubric rule: {rule_id}")
        seen.add(rule_id)
        severity_name = str(row.get("severity") or "").lower()
        if severity_name not in _SEVERITIES:
            raise ValueError(f"{rule_id}: unknown severity {severity_name!r}")
        check_name = str(row.get("check") or "").strip()
        if not check_name:
            raise ValueError(f"{rule_id}: missing check name")
        applies = row.get("applies_to") or {}
        params = dict(row.get("params") or {})
        if params.get("constants") == config.RUBRIC_CONSTANTS_KEY:
            params["constants"] = list(constants)
        rules.append(
            Rule(
                id=rule_id,
                severity=_SEVERITIES[severity_name],
                check=check_name,
                scenarios=_as_tuple(applies.get("scenarios"), "scenarios"),
                prompts=_as_tuple(applies.get("prompts"), "prompts"),
                params=params,
            )
        )

    unknown = tuple(rule.id for rule in rules if rule.check not in checks.REGISTRY)
    return Rubric(
        version=str(document.get("version") or "unversioned"),
        source=str(document.get("source") or ""),
        rules=tuple(rules),
        constants=constants,
        judge=dict(document.get("judge") or {}),
        sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        unknown_rules=unknown,
        text=raw,
        recall=dict(document.get("known_recall_gaps") or {}),
    )


@lru_cache(maxsize=1)
def _prompt_texts() -> Mapping[str, str]:
    """Prompt id -> verbatim text, read once from the frozen fixture."""
    from ..fixtures import load_prompts

    try:
        return {prompt.id: prompt.text for prompt in load_prompts()}
    except (OSError, ValueError, KeyError):
        # A missing prompt fixture must not crash scoring; S-03/S-04 then lose
        # their restatement exemption, which is visible in the outcomes.
        return {}


def prompt_text(prompt_id: str) -> str:
    """The frozen prompt text, or ``""`` when the fixture cannot be read."""
    return _prompt_texts().get(prompt_id, "")


def _params_for(
    rule: Rule,
    record: Mapping[str, object],
    fixture: object,
    rubric: Rubric,
    raw_dir: Path | None,
    evidence: grounding.Evidence | None,
    visible: grounding.Visible | None,
) -> dict:
    params = dict(rule.params)
    params["_evidence"] = evidence
    params["_visible"] = visible
    params["_constants"] = list(rubric.constants)
    params["_prompt_text"] = prompt_text(
        str((record.get("prompt") or {}).get("id") or "")
    )
    return params


def apply_rubric(
    record: Mapping[str, object],
    fixture: object,
    rubric: Rubric,
    *,
    raw_dir: Path | None = None,
) -> list[RuleOutcome]:
    """Run every rule in file order against one record.

    The evidence bundle and the visible-payload view are built once per record.
    ``applies=False`` rules are returned, not dropped: the report shows how many
    cells each rule skipped, and an unearned pass is the failure mode this
    guards against.
    """
    scenario = str((record.get("fixture") or {}).get("scenario") or "")
    prompt = str((record.get("prompt") or {}).get("id") or "")
    evidence = grounding.build_evidence(record, fixture, raw_dir)
    visible = grounding.visibility(record, fixture)
    outcomes: list[RuleOutcome] = []
    for rule in rubric.rules:
        if not rule.applies_to(scenario, prompt):
            outcomes.append(
                RuleOutcome(
                    rule_id=rule.id,
                    severity=rule.severity,
                    applies=False,
                    passed=None,
                    hits=0,
                    total=0,
                    detail=f"not applicable to {scenario}/{prompt}",
                    skipped_reason="not_applicable",
                )
            )
            continue
        if rule.check not in checks.REGISTRY:
            outcomes.append(
                RuleOutcome(
                    rule_id=rule.id,
                    severity=rule.severity,
                    applies=False,
                    passed=None,
                    hits=0,
                    total=0,
                    detail=f"no implementation for check {rule.check!r}",
                    skipped_reason="unknown_rule",
                )
            )
            continue
        params = _params_for(rule, record, fixture, rubric, raw_dir, evidence, visible)
        outcome = checks.REGISTRY[rule.check](record, fixture, params)
        if outcome.rule_id != rule.id:
            raise ValueError(
                f"check {rule.check!r} returned {outcome.rule_id!r} for rule {rule.id!r}"
            )
        outcomes.append(outcome)
    return outcomes


def unknown_rules_in(outcomes: Iterable[RuleOutcome]) -> list[str]:
    """Rule ids that had no implementation on this cell."""
    return [
        outcome.rule_id
        for outcome in outcomes
        if outcome.skipped_reason == "unknown_rule"
    ]
