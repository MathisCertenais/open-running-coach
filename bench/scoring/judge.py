"""Blind LLM judge: rubric §8 and the final design in §12.5.

The judge scores usability only. It is blind to model identity, the scenario
label, and every deterministic outcome: its payload is exactly the five keys in
§12.5.3. Three calls per answer give a median per dimension; a dimension whose
repeats span two or more points gets one more call, and a cell that is still
unstable is excluded (``judge-unstable``) rather than averaged. An invalid reply
gets one retry, then the cell is ``judge-invalid`` with **no imputed score**.

Before scoring candidates, the same loop must reproduce three hand-scored
answers within +/-1 on every dimension (rubric §8.5, §12.5.4). If it cannot,
the run does not produce a verdict.

The prompt text, anchors, weights and retry knobs live in ``rubric.json``'s
``judge`` block; this module never carries a second copy of them.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from .. import config
from ..plan import sha256_text
from .judge_client import JudgeClient, JudgeReply

DIMENSIONS = (
    "actionability",
    "specificity",
    "prioritisation",
    "honesty",
    "tone",
)
_CONFIDENCE = frozenset({"high", "medium", "low"})
_TOP_KEYS = frozenset({"scores", "rationale", "quotes", "confidence"})


@dataclass(frozen=True)
class JudgeCall:
    """One HTTP turn of the judge, with the budget it was given."""

    max_tokens: int
    finish_reason: str | None
    reasoning_chars: int
    outcome: str
    reply_sha256: str = ""


@dataclass(frozen=True)
class JudgeCell:
    """What the judge produced for one answer.

    ``dimensions`` is ``None`` unless ``status == "ok"``. An unstable or invalid
    cell carries no score, by design: imputing one would hide exactly the
    uncertainty the repeats exist to measure.
    """

    status: str
    dimensions: Mapping[str, float] | None
    calls: int
    reply_sha256: tuple[str, ...]
    detail: str = ""
    unstable_dimensions: tuple[str, ...] = ()
    call_log: tuple[JudgeCall, ...] = ()


@dataclass(frozen=True)
class CalibrationAnswer:
    """One calibration answer's parsed calls, medians and signed errors."""

    id: str
    scenario: str
    status: str
    calls: Mapping[str, tuple[int, ...]]
    hand: Mapping[str, float]
    medians: Mapping[str, float]
    ranges: Mapping[str, int]
    errors: Mapping[str, float]
    bias: float
    detail: str = ""
    call_log: tuple[JudgeCall, ...] = ()


@dataclass(frozen=True)
class CalibrationResult:
    """Gate J2 (rubric §12.7): the provisional certification of the judge.

    ``details`` stays the JSON-shaped per-answer record the score pass writes;
    ``answers`` carries the per-dimension calls the gate actually evaluated.
    """

    passed: bool
    details: tuple[dict, ...]
    judge_model: str
    prompt_sha256: str
    gate: str = config.JUDGE_GATE
    conditions: Mapping[str, bool] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    answers: tuple[CalibrationAnswer, ...] = ()
    worst_bias: float = 0.0
    within_one: int = 0
    total_pairs: int = 0


def judge_prompt(judge: Mapping[str, object]) -> str:
    """The canonical system prompt, read from the rubric's judge block."""
    prompt = str(judge.get("prompt") or "")
    if not prompt:
        raise ValueError("rubric.json has no judge.prompt")
    return prompt


def judge_prompt_sha256(judge: Mapping[str, object]) -> str:
    return sha256_text(judge_prompt(judge))


def _calls(judge: Mapping[str, object]) -> int:
    return int(judge.get("calls_per_answer") or config.JUDGE_CALLS_PER_ANSWER)


def _extra_calls(judge: Mapping[str, object]) -> int:
    return int(judge.get("extra_calls") or config.JUDGE_EXTRA_CALLS)


def _unstable_span(judge: Mapping[str, object]) -> int:
    return int(judge.get("unstable_span") or config.JUDGE_UNSTABLE_SPAN)


def _rationale_words(judge: Mapping[str, object]) -> int:
    return int(judge.get("rationale_max_words") or config.JUDGE_RATIONALE_MAX_WORDS)


_DIMENSION_IDS = {
    "J-01": "actionability",
    "J-02": "specificity",
    "J-03": "prioritisation",
    "J-04": "honesty",
    "J-05": "tone",
}


def judge_weights(judge: Mapping[str, object]) -> dict[str, float]:
    """Dimension -> weight, read from the rubric's judge block.

    The rubric names the dimensions J-01..J-05; the code uses the human names.
    The order and values are the ruling's (0.30/0.20/0.15/0.25/0.10); this
    module never restates the numbers.
    """
    names = judge.get("dimensions") or []
    weights = judge.get("weights") or []
    if len(names) != len(DIMENSIONS) or len(weights) != len(DIMENSIONS):
        raise ValueError("rubric.json judge block must name five weights")
    return {
        _DIMENSION_IDS.get(str(name), str(name)): float(weight)
        for name, weight in zip(names, weights)
    }


def _max_tokens(judge: Mapping[str, object]) -> int:
    """The transport budget: the configured floor, never below the rubric's."""
    configured = int(judge.get("max_tokens") or 0)
    return max(configured, config.JUDGE_MAX_TOKENS)


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------


def build_payload(
    record: Mapping[str, object],
    fixture: object,
    prompt_text: str,
    tool_results: Sequence[object] | None = None,
) -> dict:
    """Exactly the five keys §12.5.3 allows, and nothing else.

    ``athlete_data`` is the inner snapshot object, never the fixture file's
    ``meta`` block. ``tool_results`` are the full results in call order; a
    caller that only has a 400-character preview must pass ``None`` so the cell
    is refused, not judged on an incomplete bundle.
    """
    if isinstance(fixture, Mapping) and "snapshot" in fixture:
        snapshot = fixture.get("snapshot")
    else:
        snapshot = getattr(fixture, "snapshot", fixture)
    return {
        "athlete_data": snapshot,
        "tool_results": list(tool_results or []),
        "question": prompt_text,
        "answer": str(record.get("answer") or ""),
        "truncated": record.get("finish_reason") == "length",
    }


def load_tool_results(
    raw_dir: Path | None, record: Mapping[str, object]
) -> list[object] | None:
    """Full tool results from ``raw/<record_id>.jsonl``, or ``None``.

    ``None`` means "the record has tool calls but the full results were not
    retained", which makes the cell ``judge-invalid`` (rubric §12.5.3). It is
    different from ``[]``, which means "no tool calls".
    """
    calls = record.get("tool_calls") or []
    if not calls:
        return []
    if raw_dir is None:
        return None
    record_id = str(record.get("record_id") or "")
    path = raw_dir / f"{record_id}.jsonl"
    if not record_id or not path.exists():
        return None
    results: list[object] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            return None
        if isinstance(payload, Mapping) and "result" in payload:
            results.append(payload["result"])
        else:
            results.append(payload)
    return results


# ---------------------------------------------------------------------------
# Schema validation (rubric §12.5.2)
# ---------------------------------------------------------------------------


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _balanced_end(text: str, start: int) -> int | None:
    """End index of the balanced JSON object that starts at ``start``."""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def extract_json_object(raw: str) -> tuple[dict | None, str]:
    """Extract the first JSON object from a judge reply.

    Accepts a bare object, a fenced block, or an object wrapped in prose: the
    real judge prepended commentary ("Here is the JSON: …") and the old strict
    ``startswith("{")`` check threw the verdict away. The scanner respects
    strings and escapes, so a brace inside a quote cannot end the object early.
    """
    text = raw.strip()
    candidates: list[str] = []
    for match in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL):
        candidates.append(match.group(1))
    start = text.find("{")
    while start != -1:
        end = _balanced_end(text, start)
        if end is not None:
            candidate = text[start:end]
            if candidate not in candidates:
                candidates.append(candidate)
            break
        start = text.find("{", start + 1)
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value, ""
    return None, "no JSON object found in the reply"


def parse_reply(
    raw: str,
    answer: str,
    *,
    rationale_max_words: int = config.JUDGE_RATIONALE_MAX_WORDS,
    extreme_min_words: int = config.JUDGE_EXTREME_RATIONALE_WORDS,
) -> tuple[dict | None, str]:
    """Validate one judge reply, returning ``(parsed, error)``.

    Extraction accepts prose and fences; validation then follows §12.5.2:
    keys, score types and ranges, rationale length, verbatim quotes, the 1/5
    rationale floor, confidence. The 1/5 rule is machine-checkable on purpose:
    a rationale of at least ``extreme_min_words`` words plus a verbatim quote
    pair replaces the fuzzy "quotes or names a span" heuristic the real judge
    could not satisfy.
    """
    payload, error = extract_json_object(raw)
    if payload is None:
        return None, error
    if frozenset(payload) != _TOP_KEYS:
        return None, "expected exactly scores, rationale, quotes, confidence"

    scores = payload.get("scores")
    rationale = payload.get("rationale")
    quotes = payload.get("quotes")
    confidence = payload.get("confidence")
    if not all(isinstance(item, Mapping) for item in (scores, rationale, quotes)):
        return None, "scores, rationale and quotes must be objects"
    if frozenset(scores) != frozenset(DIMENSIONS):
        return None, "scores must carry exactly the five dimensions"
    if frozenset(rationale) != frozenset(DIMENSIONS):
        return None, "rationale must carry exactly the five dimensions"

    for dimension in DIMENSIONS:
        value = scores[dimension]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
            return None, f"{dimension} is not an integer in 1..5"
        text = rationale[dimension]
        if not isinstance(text, str) or not text.strip():
            return None, f"{dimension} has an empty rationale"
        if len(text.split()) > rationale_max_words:
            return None, f"{dimension} rationale exceeds {rationale_max_words} words"

    if frozenset(quotes) != {"strongest", "weakest"}:
        return None, "quotes must carry exactly strongest and weakest"
    collapsed_answer = _collapse(answer)
    for key in ("strongest", "weakest"):
        quote = quotes.get(key)
        if not isinstance(quote, str) or not quote.strip():
            return None, f"quotes.{key} is empty"
        if _collapse(quote) not in collapsed_answer:
            return None, f"quotes.{key} is not a verbatim substring of the answer"

    for dimension in DIMENSIONS:
        if scores[dimension] not in (1, 5):
            continue
        words = len(str(rationale[dimension]).split())
        if words < extreme_min_words:
            return None, (
                f"{dimension} scores {scores[dimension]} but its rationale has "
                f"{words} word(s), under the {extreme_min_words}-word floor"
            )
    if confidence not in _CONFIDENCE:
        return None, "confidence must be high, medium or low"
    return payload, ""


# ---------------------------------------------------------------------------
# The call loop
# ---------------------------------------------------------------------------


def _raw_call(
    client: JudgeClient, system: str, user: str, max_tokens: int
) -> tuple[JudgeReply | None, str]:
    try:
        return client.complete(system, user, max_tokens=max_tokens), ""
    except Exception as exc:  # transport failures are data, not crashes
        return None, f"{type(exc).__name__}: {exc}"


def _one_call(
    client: JudgeClient,
    system: str,
    user: str,
    answer: str,
    *,
    max_tokens: int,
    rationale_max_words: int,
) -> tuple[dict | None, str, list[JudgeCall]]:
    """One judge reply, with exactly one retry on any failure mode.

    A reasoning-only reply retries with twice the output budget (the hidden
    tokens are the cause); a parse or contract failure retries with the
    stronger "JSON only" instruction and the rejection reason. The second
    failure ends the cell as invalid: no score is imputed.
    """
    log: list[JudgeCall] = []
    budget = max_tokens
    prompt = user
    last_error = ""
    for _attempt in range(config.JUDGE_REPLY_ATTEMPTS):
        reply, error = _raw_call(client, system, prompt, budget)
        if reply is None:
            log.append(JudgeCall(budget, None, 0, "transport_error", ""))
            return None, error or "transport failure", log
        if reply.reasoning_only:
            log.append(
                JudgeCall(
                    budget,
                    reply.finish_reason,
                    reply.reasoning_chars,
                    "reasoning_only",
                    sha256_text(reply.text),
                )
            )
            last_error = (
                "the judge spent its output budget on hidden reasoning "
                f"({reply.reasoning_chars} char(s), finish={reply.finish_reason})"
            )
            budget = min(budget * 2, config.JUDGE_MAX_TOKENS_CEILING)
            prompt = user + "\n\n" + config.JUDGE_STRONGER_INSTRUCTION
            continue
        parsed, rejection = parse_reply(
            reply.text, answer, rationale_max_words=rationale_max_words
        )
        if parsed is not None:
            log.append(
                JudgeCall(
                    budget,
                    reply.finish_reason,
                    reply.reasoning_chars,
                    "parsed",
                    sha256_text(reply.text),
                )
            )
            return parsed, "", log
        log.append(
            JudgeCall(
                budget,
                reply.finish_reason,
                reply.reasoning_chars,
                "invalid",
                sha256_text(reply.text),
            )
        )
        last_error = rejection or error or "invalid judge reply"
        prompt = (
            user
            + "\n\n"
            + config.JUDGE_STRONGER_INSTRUCTION
            + "\nYour previous reply was rejected: "
            + last_error
        )
    return None, last_error or "invalid judge reply", log


def _unstable_dimensions(
    attempts: Sequence[Mapping[str, object]], span: int
) -> tuple[str, ...]:
    unstable: list[str] = []
    for dimension in DIMENSIONS:
        values = [attempt["scores"][dimension] for attempt in attempts]
        if max(values) - min(values) >= span:
            unstable.append(dimension)
    return tuple(unstable)


def judge_payload(
    payload: Mapping[str, object],
    client: JudgeClient,
    judge: Mapping[str, object],
) -> JudgeCell:
    """Run the repeat protocol on one §12.5.3 payload."""
    system = judge_prompt(judge)
    user = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    answer = str(payload.get("answer") or "")
    max_words = _rationale_words(judge)
    attempts: list[dict] = []
    hashes: list[str] = []
    call_log: list[JudgeCall] = []
    budget = _max_tokens(judge)

    for _ in range(_calls(judge)):
        parsed, error, reply_log = _one_call(
            client,
            system,
            user,
            answer,
            max_tokens=budget,
            rationale_max_words=max_words,
        )
        call_log.extend(reply_log)
        hashes.extend(call.reply_sha256 for call in reply_log)
        if parsed is None:
            return JudgeCell(
                "judge-invalid",
                None,
                len(call_log),
                tuple(hashes),
                detail=error,
                call_log=tuple(call_log),
            )
        attempts.append(parsed)

    span = _unstable_span(judge)
    unstable = _unstable_dimensions(attempts, span)
    if unstable:
        for _ in range(_extra_calls(judge)):
            parsed, error, reply_log = _one_call(
                client,
                system,
                user,
                answer,
                max_tokens=budget,
                rationale_max_words=max_words,
            )
            call_log.extend(reply_log)
            hashes.extend(call.reply_sha256 for call in reply_log)
            if parsed is None:
                return JudgeCell(
                    "judge-invalid",
                    None,
                    len(call_log),
                    tuple(hashes),
                    detail=error,
                    call_log=tuple(call_log),
                )
            attempts.append(parsed)
        unstable = _unstable_dimensions(attempts, span)
        if unstable:
            return JudgeCell(
                "judge-unstable",
                None,
                len(call_log),
                tuple(hashes),
                detail="repeats still span >= "
                f"{span} on {', '.join(unstable)} after a fourth call",
                unstable_dimensions=unstable,
                call_log=tuple(call_log),
            )

    dimensions = {
        dimension: float(
            statistics.median([attempt["scores"][dimension] for attempt in attempts])
        )
        for dimension in DIMENSIONS
    }
    return JudgeCell(
        "ok", dimensions, len(call_log), tuple(hashes), call_log=tuple(call_log)
    )


def judge_answer(
    record: Mapping[str, object],
    fixture: object,
    prompt_text: str,
    client: JudgeClient,
    judge: Mapping[str, object],
    *,
    tool_results: Sequence[object] | None = None,
) -> JudgeCell:
    """Judge one stored answer, refusing to guess when tool results are missing."""
    calls = record.get("tool_calls") or []
    if calls and tool_results is None:
        return JudgeCell(
            "judge-invalid",
            None,
            0,
            (),
            detail=(
                "the record has tool calls but the full results were not retained; "
                "judging on a preview would misread the unseen part"
            ),
        )
    payload = build_payload(record, fixture, prompt_text, tool_results or [])
    return judge_payload(payload, client, judge)


# ---------------------------------------------------------------------------
# Independence and the calibration gate
# ---------------------------------------------------------------------------


def _normalise(value: object) -> str:
    return str(value or "").strip().lower()


def refuse_self_judging(judge_ids: Sequence[str], under_test: Sequence[object]) -> None:
    """Refuse a judge whose id is one of the models under test (rubric §8.1).

    ``under_test`` is a sequence of values that identify a model: roster key,
    registry id, provider model id. Comparing the judge's id and model against
    all of them is what stops a model from judging its own answers. A sibling
    checkpoint cannot be detected from ids alone; the report discloses the
    vendor instead.
    """
    judge_set = {_normalise(value) for value in judge_ids if _normalise(value)}
    for model in under_test:
        for candidate in _model_identifiers(model):
            normalised = _normalise(candidate)
            if normalised and normalised in judge_set:
                raise ValueError(
                    f"judge {normalised!r} is a model under test; refusing to score"
                )


def _model_identifiers(model: object) -> list[str]:
    """Every string that can name a model, from a spec or a plain value."""
    if isinstance(model, str):
        return [model]
    values: list[str] = []
    for attribute in ("key", "model", "registry_id"):
        value = getattr(model, attribute, None)
        if value:
            values.append(str(value))
    return values


def load_calibration(path: Path | None = None) -> dict:
    source = path or (config.FIXTURES_DIR / config.JUDGE_CALIBRATION_FILENAME)
    if not source.exists():
        raise FileNotFoundError(f"missing judge calibration fixture: {source}")
    document = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(document.get("answers"), list) or not document["answers"]:
        raise ValueError(f"{source} has no calibration answers")
    return document


def _calibration_payload(answer: Mapping[str, object], fixture: object) -> dict:
    """Strip ``source``, ``expected`` and ``rationale`` before the call."""
    return {
        "athlete_data": getattr(fixture, "snapshot", None),
        "tool_results": [],
        "question": str(answer.get("question") or ""),
        "answer": str(answer.get("answer") or ""),
        "truncated": False,
    }


def _parsed_scores(parsed: Mapping[str, object]) -> dict[str, int]:
    scores = parsed.get("scores") or {}
    return {dimension: int(scores[dimension]) for dimension in DIMENSIONS}


def _any_unstable(scores: Sequence[Mapping[str, int]], span: int) -> bool:
    for dimension in DIMENSIONS:
        values = [row[dimension] for row in scores]
        if len(values) >= 2 and max(values) - min(values) >= span:
            return True
    return False


def _answer_record(
    answer: Mapping[str, object],
    scores: Sequence[Mapping[str, int]],
    weights: Mapping[str, float],
    *,
    status: str,
    detail: str,
    call_log: Sequence[JudgeCall],
) -> CalibrationAnswer:
    expected = answer.get("expected") or {}
    hand = {
        dimension: float(expected.get(dimension))
        for dimension in DIMENSIONS
        if isinstance(expected.get(dimension), (int, float))
    }
    calls = {
        dimension: tuple(row[dimension] for row in scores) for dimension in DIMENSIONS
    }
    medians: dict[str, float] = {}
    ranges: dict[str, int] = {}
    errors: dict[str, float] = {}
    if len(scores) >= 3:
        for dimension in DIMENSIONS:
            values = calls[dimension]
            medians[dimension] = float(statistics.median(values))
            ranges[dimension] = max(values) - min(values)
            if dimension in hand:
                errors[dimension] = medians[dimension] - hand[dimension]
    bias = (
        sum(weights[dimension] * errors[dimension] for dimension in DIMENSIONS)
        if len(errors) == len(DIMENSIONS)
        else 0.0
    )
    return CalibrationAnswer(
        id=str(answer.get("id") or ""),
        scenario=str(answer.get("scenario") or ""),
        status=status,
        calls=calls,
        hand=hand,
        medians=medians,
        ranges=ranges,
        errors=errors,
        bias=round(bias, 6),
        detail=detail,
        call_log=tuple(call_log),
    )


def _condition_failures(
    answers: Sequence[CalibrationAnswer], weights: Mapping[str, float]
) -> tuple[dict[str, bool], list[str], int, int, float]:
    """The six J2 conditions, their reasons, and the summary numbers."""
    failures: list[str] = []
    conditions: dict[str, bool] = {}

    # V — all three answers produced at least three parsed calls.
    v_ok = True
    for answer in answers:
        parsed = min((len(values) for values in answer.calls.values()), default=0)
        if answer.status != "ok" or parsed < 3:
            v_ok = False
            failures.append(
                f"V: {answer.id} returned {parsed} parsed call(s) "
                f"(status {answer.status}){': ' + answer.detail if answer.detail else ''}"
            )
    conditions["V"] = v_ok

    # A — the heavy dimensions are within +/-1.
    a_ok = True
    for answer in answers:
        for dimension, weight in weights.items():
            if weight < config.JUDGE_GATE_A_WEIGHT:
                continue
            error = answer.errors.get(dimension)
            if error is None:
                a_ok = False
                failures.append(
                    f"A: {answer.id} {dimension} has no median (status {answer.status})"
                )
            elif abs(error) > 1:
                a_ok = False
                failures.append(
                    f"A: {answer.id} {dimension} e={error:+g} "
                    f"(weight {weight:g}, needs |e| <= 1)"
                )
    conditions["A"] = a_ok

    # T — at most one |e| >= 2, and only on a light dimension.
    t_pairs = [
        (answer.id, dimension, answer.errors[dimension], weights[dimension])
        for answer in answers
        for dimension in DIMENSIONS
        if dimension in answer.errors and abs(answer.errors[dimension]) >= 2
    ]
    t_ok = len(t_pairs) <= config.JUDGE_GATE_T_MAX and all(
        weight <= config.JUDGE_GATE_T_WEIGHT for _id, _d, _e, weight in t_pairs
    )
    if not t_ok:
        failures.append(
            "T: "
            + "; ".join(
                f"{answer_id} {dimension} e={error:+g} at weight {weight:g}"
                for answer_id, dimension, error, weight in t_pairs
            )
        )
    conditions["T"] = t_ok

    # B — the signed weighted error per answer is bounded.
    b_ok = True
    for answer in answers:
        if abs(answer.bias) > config.JUDGE_GATE_B_MAX:
            b_ok = False
            failures.append(
                f"B: {answer.id} signed bias {answer.bias:+.3f} "
                f"(needs |B| <= {config.JUDGE_GATE_B_MAX:g})"
            )
    conditions["B"] = b_ok

    # S — the judge separates the 5-answer from the 1-answer.
    cal05 = next((a for a in answers if a.id.startswith("cal-05")), None)
    cal01 = next((a for a in answers if a.id.startswith("cal-01")), None)
    if cal05 is None or cal01 is None or not cal05.medians or not cal01.medians:
        s_ok = False
        failures.append("S: cal-05 or cal-01 is missing a median")
    else:
        separation = sum(
            1
            for dimension in DIMENSIONS
            if cal05.medians[dimension] - cal01.medians[dimension]
            >= config.JUDGE_GATE_S_SPAN
        )
        s_ok = separation >= config.JUDGE_GATE_S_MIN
        if not s_ok:
            failures.append(
                f"S: only {separation} dimension(s) separate cal-05 from cal-01 "
                f"by >= {config.JUDGE_GATE_S_SPAN} (need {config.JUDGE_GATE_S_MIN})"
            )
    conditions["S"] = s_ok

    # U — at most one unstable dimension, and only on a light one.
    u_pairs = [
        (answer.id, dimension, answer.ranges[dimension], weights[dimension])
        for answer in answers
        for dimension in DIMENSIONS
        if dimension in answer.ranges and answer.ranges[dimension] >= 2
    ]
    u_ok = len(u_pairs) <= config.JUDGE_GATE_U_MAX and all(
        weight < config.JUDGE_GATE_U_WEIGHT for _id, _d, _r, weight in u_pairs
    )
    if not u_ok:
        failures.append(
            "U: "
            + "; ".join(
                f"{answer_id} {dimension} range={span} at weight {weight:g}"
                for answer_id, dimension, span, weight in u_pairs
            )
        )
    conditions["U"] = u_ok

    within_one = sum(
        1
        for answer in answers
        for dimension in DIMENSIONS
        if dimension in answer.errors and abs(answer.errors[dimension]) <= 1
    )
    total = len(answers) * len(DIMENSIONS)
    worst_bias = max((abs(answer.bias) for answer in answers), default=0.0)
    return conditions, failures, within_one, total, worst_bias


def evaluate_gate_j2(
    answers: Sequence[CalibrationAnswer],
    weights: Mapping[str, float],
) -> dict:
    """Apply the six J2 conditions and return the verdict and its reasons.

    J2 is a documented relaxation of §8.5 (rubric §12.7): it bounds the
    published metric (|B| <= 0.25) instead of rejecting on any single cell.
    Nothing here reads the clock, the network or the scores file, which is what
    makes the gate table-testable.
    """
    conditions, failures, within_one, total, worst = _condition_failures(
        answers, weights
    )
    return {
        "gate": config.JUDGE_GATE,
        "passed": all(conditions.values()),
        "conditions": conditions,
        "reasons": tuple(failures),
        "within_one": within_one,
        "total_pairs": total,
        "worst_bias": worst,
    }


def _detail_dict(answer: CalibrationAnswer, judge: Mapping[str, object]) -> dict:
    """The JSON-shaped record the score pass stores in meta.json."""
    return {
        "id": answer.id,
        "scenario": answer.scenario,
        "status": answer.status,
        "judge": dict(answer.medians) if answer.medians else None,
        "expected": dict(answer.hand) if answer.hand else None,
        "mismatches": [
            f"{dimension}: judge {answer.medians[dimension]:g} vs "
            f"hand {answer.hand[dimension]:g}"
            for dimension in DIMENSIONS
            if dimension in answer.errors and abs(answer.errors[dimension]) > 1
        ],
        "per_dimension": {
            dimension: {
                "calls": list(answer.calls.get(dimension, ())),
                "median": answer.medians.get(dimension),
                "range": answer.ranges.get(dimension),
                "hand": answer.hand.get(dimension),
                "error": answer.errors.get(dimension),
            }
            for dimension in DIMENSIONS
        },
        "bias": answer.bias,
        "max_tokens": _max_tokens(judge),
        "calls": len(answer.call_log),
        "attempts": len(answer.call_log),
        "call_log": [
            {
                "max_tokens": call.max_tokens,
                "finish_reason": call.finish_reason,
                "reasoning_chars": call.reasoning_chars,
                "outcome": call.outcome,
            }
            for call in answer.call_log
        ],
        "detail": answer.detail,
    }


def run_calibration(
    client: JudgeClient,
    judge: Mapping[str, object],
    fixtures: Mapping[str, object],
    *,
    path: Path | None = None,
) -> CalibrationResult:
    """Run the calibration answers through the repeat protocol and apply J2.

    Three calls per answer, then one extra call while any dimension is still
    unstable, up to the configured cap. Every parsed score is kept: J2 needs
    the medians *and* the ranges, and V needs to know whether every answer
    produced at least three parsed calls. The §8.5 gate is gone.
    """
    document = load_calibration(path)
    weights = judge_weights(judge)
    system = judge_prompt(judge)
    max_words = _rationale_words(judge)
    budget = _max_tokens(judge)
    span = _unstable_span(judge)
    answers: list[CalibrationAnswer] = []
    details: list[dict] = []

    for answer in document["answers"]:
        scenario = str(answer.get("scenario") or "")
        fixture = fixtures.get(scenario)
        if fixture is None:
            record = _answer_record(
                answer, [], weights, status="missing_fixture", detail="", call_log=[]
            )
            answers.append(record)
            details.append(_detail_dict(record, judge))
            continue
        payload = _calibration_payload(answer, fixture)
        user = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        scores: list[dict[str, int]] = []
        call_log: list[JudgeCall] = []
        status = "ok"
        detail = ""
        for _ in range(_calls(judge)):
            parsed, error, reply_log = _one_call(
                client,
                system,
                user,
                str(payload.get("answer") or ""),
                max_tokens=budget,
                rationale_max_words=max_words,
            )
            call_log.extend(reply_log)
            if parsed is None:
                status = (
                    "transport_error"
                    if reply_log and reply_log[-1].outcome == "transport_error"
                    else "judge-invalid"
                )
                detail = error
                break
            scores.append(_parsed_scores(parsed))
        extras = 0
        while (
            status == "ok"
            and _any_unstable(scores, span)
            and extras < config.JUDGE_CALIBRATION_EXTRA_CALLS
        ):
            parsed, error, reply_log = _one_call(
                client,
                system,
                user,
                str(payload.get("answer") or ""),
                max_tokens=budget,
                rationale_max_words=max_words,
            )
            call_log.extend(reply_log)
            extras += 1
            if parsed is None:
                status = (
                    "transport_error"
                    if reply_log and reply_log[-1].outcome == "transport_error"
                    else "judge-invalid"
                )
                detail = error
                break
            scores.append(_parsed_scores(parsed))
        record = _answer_record(
            answer,
            scores,
            weights,
            status=status,
            detail=detail,
            call_log=call_log,
        )
        answers.append(record)
        details.append(_detail_dict(record, judge))

    conditions, failures, within_one, total, worst_bias = _condition_failures(
        answers, weights
    )
    passed = all(conditions.values())
    return CalibrationResult(
        passed=passed,
        details=tuple(details),
        judge_model=str(getattr(client, "model_id", "")),
        prompt_sha256=judge_prompt_sha256(judge),
        gate=config.JUDGE_GATE,
        conditions=conditions,
        reasons=tuple(failures),
        answers=tuple(answers),
        worst_bias=worst_bias,
        within_one=within_one,
        total_pairs=total,
    )
