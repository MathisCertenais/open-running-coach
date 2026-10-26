"""Deterministic scoring: rubric loader, check registry, aggregation.

This package implements spec §7.1-§7.4 and rubric §4, §5 and §9. It never calls
a model: rescoring after a rubric change is free and idempotent, which is the
property that makes a stored sweep auditable months later.
"""

from __future__ import annotations

from .aggregate import (
    SCORE_SCHEMA_VERSION,
    aggregate,
    compare_models,
    composite,
    judge_value,
    latest_records,
    score_answer,
    score_records,
    scores_jsonl,
    summarise_model,
    unscored_entry,
    write_scores,
)
from .checks import REGISTRY, RuleOutcome, Severity
from .grounding import Evidence, build_evidence, extract_numbers, ground
from .rubric import Rubric, Rule, apply_rubric, load_rubric, unknown_rules_in

__all__ = [
    "Evidence",
    "REGISTRY",
    "Rubric",
    "Rule",
    "RuleOutcome",
    "SCORE_SCHEMA_VERSION",
    "Severity",
    "aggregate",
    "apply_rubric",
    "build_evidence",
    "compare_models",
    "composite",
    "extract_numbers",
    "ground",
    "judge_value",
    "latest_records",
    "load_rubric",
    "score_answer",
    "score_records",
    "scores_jsonl",
    "summarise_model",
    "unknown_rules_in",
    "unscored_entry",
    "write_scores",
]
