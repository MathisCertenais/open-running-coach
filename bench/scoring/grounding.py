"""Number extraction and comparison against the evidence bundle.

Grounding is the check that decides whether this benchmark is credible. One
extractor classifies every number in an answer (percent, ratio, load, pace,
duration, distance, prediction, count, date, year) and one comparator decides
whether the evidence bundle contains it within the class tolerance of rubric
§4.2.1. Writing eight ad-hoc regexes in eight checks is how a benchmark ends up
with eight different opinions about what "1.6" means.

The bundle is the fixture snapshot, the tool results that were actually
returned to the model, and the declared constants of rubric §1.2. Numbers the
model derived itself are never evidence: they are found by
``arithmetic_claims`` and scored by G-02 instead.

When a tool result was stored as a 400-character preview, a number that does
not match may live in the part that was not kept. It is then reported as
``unknown`` rather than failed, and the count travels with the outcome so the
report can say how much of a score rests on previews (spec §7.1).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

from .. import config

# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------

_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n\s*\n")
# "Smithson et al. (2019)" must stay one sentence, or an author loses its year
# and a fabricated citation looks like a bare name.
_ABBREVIATIONS = ("et al.", "e.g.", "i.e.", "vs.", "Dr.", "Mr.", "Ms.", "No.")


def sentences(text: str) -> list[str]:
    """Split prose into sentences, keeping markdown lines intact.

    A bullet is its own sentence: an answer's claims live in bullets, and
    joining two bullets would let a number in one justify a claim in the other.
    Latin abbreviations ("et al.") do not end a sentence.
    """
    protected = text
    for abbreviation in _ABBREVIATIONS:
        protected = protected.replace(abbreviation, abbreviation[:-1] + "\u2024")
    parts: list[str] = []
    for block in _SENTENCE_BREAK.split(protected):
        stripped = block.strip()
        if stripped:
            parts.append(stripped.replace("\u2024", "."))
    return parts


def paragraphs(text: str) -> list[str]:
    """Split on blank lines; a bullet list is one paragraph."""
    return [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]


def section_of(text: str, position: int) -> str | None:
    """Which ``SYSTEM_PROMPT`` section a character offset falls under.

    Used by G-01's severity: an ungrounded number in the Assessment is a
    blocker, one in a bullet is a major. Returns the normalised section name.
    """
    headers = list(_HEADER.finditer(text))
    current: str | None = None
    for header in headers:
        if header.start() > position:
            break
        current = header.group("name").lower()
    return _normalise_section(current) if current else None


_HEADER = re.compile(
    r"^\s*(?:#{1,6}\s*|\*\*|__)?\s*"
    r"(?P<name>assessment|what the data says|recommendations?|watch[- ]?outs?)"
    r"\s*(?:\*\*|__)?\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_SECTION_ALIASES = {
    "assessment": "assessment",
    "what the data says": "data",
    "recommendation": "recommendations",
    "recommendations": "recommendations",
    "watch-out": "watchouts",
    "watch-outs": "watchouts",
    "watchout": "watchouts",
    "watchouts": "watchouts",
    "watch out": "watchouts",
    "watch outs": "watchouts",
}


def _normalise_section(name: str | None) -> str | None:
    if name is None:
        return None
    return _SECTION_ALIASES.get(name.strip())


def parse_text_date(raw: str) -> tuple[int, int, int | None] | None:
    """Parse ``26 Oct`` / ``Oct 26`` / ``26 October 2026`` into (month, day, year)."""
    lowered = raw.lower().strip()
    match = re.match(
        r"(?P<day>\d{1,2})\s+(?P<month>[a-z]+)\.?(?:\s+(?P<year>\d{4}))?",
        lowered,
    )
    if match and match.group("month") in _MONTHS:
        year = match.group("year")
        return (
            _MONTHS[match.group("month")],
            int(match.group("day")),
            int(year) if year else None,
        )
    match = re.match(
        r"(?P<month>[a-z]+)\.?\s+(?P<day>\d{1,2})(?:,?\s+(?P<year>\d{4}))?",
        lowered,
    )
    if match and match.group("month") in _MONTHS:
        year = match.group("year")
        return (
            _MONTHS[match.group("month")],
            int(match.group("day")),
            int(year) if year else None,
        )
    return None


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

# Ordered longest-first: the unit alternation must try "minutes" before "min"
# and "km" before "m", or every minute becomes a metre.
_UNITS = (
    "ml/kg/min",
    "kilometres",
    "kilometers",
    "km/h",
    "kcal",
    "minutes",
    "minute",
    "metres",
    "meters",
    "mins",
    "miles",
    "mile",
    "min",
    "hrs",
    "hours",
    "hour",
    "secs",
    "seconds",
    "bpm",
    "kg",
    "mi",
    "mg",
    "IU",
    "km",
    "m",
    "h",
    "s",
    "%",
)
_UNIT_PATTERN = "|".join(re.escape(unit) for unit in _UNITS)

_TOKEN = re.compile(
    r"(?P<iso>(?<![\d.])\d{4}-\d{2}-\d{2}(?![\d.]))"
    r"|(?P<hms>(?<![\d:])\d{1,2}:\d{2}:\d{2}(?![\d:]))"
    r"|(?P<ms>(?<![\d:])\d{1,3}:\d{2}(?![\d:]))"
    r"|(?P<num>(?<![\d.A-Za-z_])"
    r"(?P<sign>[-−+])?"
    r"(?P<digits>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<unit>\s*(?:" + _UNIT_PATTERN + r")(?![A-Za-z]))?"
    r"(?P<k>k(?![A-Za-z]))?"
    r")"
)

_MONTH_DAY = re.compile(r"(?<![\d.])(?P<month>\d{1,2})-(?P<day>\d{1,2})(?![\d.])")
_DATE_CONTEXT = re.compile(
    r"\b(on|during|since|from|until|by|and|or|between|after|before|reported)\s+$",
    re.IGNORECASE,
)
_UNIT_FOLLOW = re.compile(
    r"^\s*(min|mins|minutes|km|m|%|weeks?|days?|reps?|sets?|hours?|h)\b",
    re.IGNORECASE,
)

_DATE_RANGE_PREFIX = re.compile(
    r"\b(?P<month>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+"
    r"(?P<low>\d{1,2})\s*[-–—]\s*(?P<high>\d{1,2})\b",
    re.IGNORECASE,
)
_DATE_RANGE = re.compile(
    r"\b(?P<low>\d{1,2})\s*[-–—]\s*(?P<high>\d{1,2})\s+"
    r"(?P<month>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b",
    re.IGNORECASE,
)

_TEXTUAL_DATE = re.compile(
    r"\b(?:\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2})"
    r"(?:,?\s+\d{4})?\b",
    re.IGNORECASE,
)

# A range such as "42-44 minutes" is one claim, not two: the true value may sit
# anywhere between the endpoints.
_RANGE_GAP = re.compile(r"^\s*(?:-|–|—|to)\s*$", re.IGNORECASE)

_LOAD_CONTEXT = re.compile(
    r"\b(load|loads|ctl|atl|tsb|units?|fitness|fatigue|form|acute|chronic|"
    r"training load|session load)\b",
    re.IGNORECASE,
)
_RATIO_CONTEXT = re.compile(
    r"\b(ratio|acute[:\s-]*chronic|acwr|load change|load-change|\d+x\b|times)\b",
    re.IGNORECASE,
)
_COUNT_CONTEXT = re.compile(
    r"\b(runs?|sessions?|episodes?|days?|weeks?|times|activities|rpe|reports?)\b",
    re.IGNORECASE,
)
_SCALE_CONTEXT = re.compile(r"\b(rpe|readiness|energy|effort)\b", re.IGNORECASE)
_PREDICTION_CONTEXT = re.compile(
    r"\b(10\s?k|10\s?km|ten[- ]k|predict\w*|race time|finish(?:ing)? time)\b",
    re.IGNORECASE,
)
_PACE_CONTEXT = re.compile(r"(/km|/mi|per km|per mile|pace)", re.IGNORECASE)


@dataclass(frozen=True)
class Mention:
    """One number in the answer, classified, with the text around it."""

    raw: str
    value: float | None
    kind: str
    start: int
    end: int
    unit: str | None
    before: str
    after: str
    sentence: str
    decimals: int
    significant_decimals: int = 0
    range_low: float | None = None
    range_high: float | None = None
    date_value: date | None = None
    notation: bool = False

    @property
    def context(self) -> str:
        """The ~40 characters before and after, for evidence quotes."""
        return f"{self.before}…{self.raw}…{self.after}"


def _kind_for_context(value: float, integer: bool, before: str, after: str) -> str:
    if _RATIO_CONTEXT.search(before) and 0.5 <= abs(value) <= 3.0:
        return "ratio"
    if _LOAD_CONTEXT.search(before):
        return "load"
    if _SCALE_CONTEXT.search(before):
        if 0 <= value <= 10:
            return "scale"
        if 1 <= value <= 5:
            return "scale"
    if _PACE_CONTEXT.search(before) or _PACE_CONTEXT.search(after):
        return "pace"
    if integer and _COUNT_CONTEXT.search(before):
        return "count"
    if integer and 1900 <= value <= 2099:
        return "year"
    return "plain"


def _sentence_at(text: str, start: int, end: int) -> str:
    left = max(
        text.rfind("\n", 0, start),
        text.rfind(". ", 0, start),
        text.rfind("! ", 0, start),
        text.rfind("? ", 0, start),
    )
    right_candidates = [
        index
        for index in (
            text.find("\n", end),
            text.find(". ", end),
            text.find("! ", end),
            text.find("? ", end),
        )
        if index != -1
    ]
    right = min(right_candidates) if right_candidates else len(text)
    return text[left + 1 : right + 1].strip()


def extract_numbers(text: str) -> list[Mention]:
    """Extract and classify every number in one answer.

    Dates and clock times are recognised before plain numbers so that
    ``2026-10-26`` is one date and ``42:34`` is one duration, not five numbers.
    """
    mentions: list[Mention] = []
    for match in _TOKEN.finditer(text):
        before = text[max(0, match.start() - 40) : match.start()]
        after = text[match.end() : match.end() + 20]
        if match.group("iso"):
            try:
                parsed = date.fromisoformat(match.group("iso"))
            except ValueError:
                continue
            mentions.append(
                Mention(
                    raw=match.group("iso"),
                    value=None,
                    kind="date",
                    start=match.start(),
                    end=match.end(),
                    unit=None,
                    before=before,
                    after=after,
                    sentence=_sentence_at(text, match.start(), match.end()),
                    decimals=0,
                    date_value=parsed,
                )
            )
            continue
        if match.group("hms") or match.group("ms"):
            clock = match.group("hms") or match.group("ms")
            parts = [int(part) for part in clock.split(":")]
            seconds = 0
            for part in parts:
                seconds = seconds * 60 + part
            if match.group("ms") and _PREDICTION_CONTEXT.search(before):
                kind = "prediction"
            elif _PACE_CONTEXT.search(before) or _PACE_CONTEXT.search(after):
                kind = "pace"
            elif match.group("hms") and _PREDICTION_CONTEXT.search(before):
                kind = "prediction"
            else:
                kind = "duration"
            mentions.append(
                Mention(
                    raw=clock,
                    value=float(seconds),
                    kind=kind,
                    start=match.start(),
                    end=match.end(),
                    unit=None,
                    before=before,
                    after=after,
                    sentence=_sentence_at(text, match.start(), match.end()),
                    decimals=0,
                )
            )
            continue

        raw_digits = match.group("digits")
        plain = raw_digits.replace(",", "")
        value = float(plain)
        if match.group("sign") in ("-", "−"):
            value = -value
        decimals = len(plain.split(".", 1)[1]) if "." in plain else 0
        unit = (match.group("unit") or "").strip().lower() or None
        integer = decimals == 0

        if match.group("k"):
            kind, unit = "distance", "km"
        elif unit == "%":
            kind = "percent"
        elif unit in {"km", "miles", "mile", "mi", "kilometres", "kilometers"}:
            kind = "distance"
        elif unit in {"m", "metres", "meters"}:
            kind = "distance" if not _SCALE_CONTEXT.search(before) else "plain"
            if kind == "distance":
                unit = "m"
        elif unit in {"min", "mins", "minute", "minutes"}:
            kind, value = "duration", value * 60
            unit = "min"
        elif unit in {"h", "hrs", "hour", "hours"}:
            kind, value = "duration", value * 3600
            unit = "h"
        elif unit in {"s", "secs", "seconds"}:
            # "360 s/km" is a pace written in seconds, not a duration.
            if after.lstrip().startswith(("/km", "/mi", "per km", "per mile")):
                kind, unit = "pace", "s"
            else:
                kind, unit = "duration", "s"
        elif unit is not None:
            kind = "plain"
        else:
            kind = _kind_for_context(value, integer, before, after)

        mentions.append(
            Mention(
                raw=match.group("num").strip(),
                value=value,
                kind=kind,
                start=match.start(),
                end=match.end(),
                unit=unit,
                before=before,
                after=after,
                sentence=_sentence_at(text, match.start(), match.end()),
                decimals=decimals,
                significant_decimals=len(
                    plain.split(".", 1)[1].rstrip("0") if "." in plain else ""
                ),
            )
        )

    for match in _TEXTUAL_DATE.finditer(text):
        parsed = parse_text_date(match.group(0))
        if parsed is None:
            continue
        month, day, year = parsed
        try:
            value = date(year or 2000, month, day)
        except ValueError:
            continue
        mentions.append(
            Mention(
                raw=match.group(0),
                value=None,
                kind="date",
                start=match.start(),
                end=match.end(),
                unit=None,
                before=text[max(0, match.start() - 40) : match.start()],
                after=text[match.end() : match.end() + 20],
                sentence=_sentence_at(text, match.start(), match.end()),
                decimals=0,
                date_value=value,
            )
        )

    date_spans = [
        (match.start(), match.end()) for match in _TEXTUAL_DATE.finditer(text)
    ]
    for match in _MONTH_DAY.finditer(text):
        month, day = int(match.group("month")), int(match.group("day"))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            continue
        before = text[max(0, match.start() - 20) : match.start()]
        after = text[match.end() : match.end() + 12]
        if not _DATE_CONTEXT.search(before) or _UNIT_FOLLOW.search(after):
            continue
        date_spans.append((match.start(), match.end()))
        try:
            value = date(2000, month, day)
        except ValueError:
            continue
        mentions.append(
            Mention(
                raw=match.group(0),
                value=None,
                kind="date",
                start=match.start(),
                end=match.end(),
                unit=None,
                before=before,
                after=after,
                sentence=_sentence_at(text, match.start(), match.end()),
                decimals=0,
                date_value=value,
            )
        )
    for match in _DATE_RANGE_PREFIX.finditer(text):
        date_spans.append((match.start(), match.end()))
        month = _MONTHS.get(match.group("month").lower()[:3])
        if month is None:
            continue
        for day in (match.group("low"), match.group("high")):
            try:
                value = date(2000, month, int(day))
            except ValueError:
                continue
            mentions.append(
                Mention(
                    raw=match.group(0),
                    value=None,
                    kind="date",
                    start=match.start(),
                    end=match.end(),
                    unit=None,
                    before=text[max(0, match.start() - 40) : match.start()],
                    after=text[match.end() : match.end() + 20],
                    sentence=_sentence_at(text, match.start(), match.end()),
                    decimals=0,
                    date_value=value,
                )
            )
    for match in _DATE_RANGE.finditer(text):
        date_spans.append((match.start(), match.end()))
        month = _MONTHS.get(match.group("month").lower()[:3])
        if month is None:
            continue
        for day in (match.group("low"), match.group("high")):
            try:
                value = date(2000, month, int(day))
            except ValueError:
                continue
            mentions.append(
                Mention(
                    raw=match.group(0),
                    value=None,
                    kind="date",
                    start=match.start(),
                    end=match.end(),
                    unit=None,
                    before=text[max(0, match.start() - 40) : match.start()],
                    after=text[match.end() : match.end() + 20],
                    sentence=_sentence_at(text, match.start(), match.end()),
                    decimals=0,
                    date_value=value,
                )
            )
    mentions = [
        mention
        for mention in mentions
        if mention.kind == "date"
        or not any(start <= mention.start < end for start, end in date_spans)
    ]
    mentions.sort(key=lambda mention: mention.start)
    return _mark_registry_notation(text, _mark_ranges(text, mentions))


def _mark_registry_notation(text: str, mentions: list[Mention]) -> list[Mention]:
    """Flag ``80/10/10``-style tokens.

    Slash notation is a named distribution, not eight separate claims; G-01
    skips it so I-03 and P-01 can own the arithmetic of "80/10/20".
    """
    marked: list[Mention] = []
    for mention in mentions:
        left = text[: mention.start].rstrip()
        right = text[mention.end :].lstrip()
        if left.endswith("/") or right.startswith("/"):
            marked.append(_replace_notation(mention))
        else:
            marked.append(mention)
    return marked


def _replace_notation(mention: Mention) -> Mention:
    return Mention(
        raw=mention.raw,
        value=mention.value,
        kind=mention.kind,
        start=mention.start,
        end=mention.end,
        unit=mention.unit,
        before=mention.before,
        after=mention.after,
        sentence=mention.sentence,
        decimals=mention.decimals,
        significant_decimals=mention.significant_decimals,
        range_low=mention.range_low,
        range_high=mention.range_high,
        date_value=mention.date_value,
        notation=True,
    )


def _mark_ranges(text: str, mentions: list[Mention]) -> list[Mention]:
    """Mark both endpoints of a numeric range with the range they span."""
    result = list(mentions)
    for index in range(len(result) - 1):
        first, second = result[index], result[index + 1]
        gap = text[first.end : second.start]
        if not _RANGE_GAP.match(gap):
            continue
        if first.value is None or second.value is None:
            continue
        low, high = sorted((first.value, second.value))
        if high - low > max(1.0, abs(low) * 0.6):
            continue
        result[index] = _replace_range(first, low, high)
        result[index + 1] = _replace_range(second, low, high)
    return result


def _replace_range(mention: Mention, low: float, high: float) -> Mention:
    return Mention(
        raw=mention.raw,
        value=mention.value,
        kind=mention.kind,
        start=mention.start,
        end=mention.end,
        unit=mention.unit,
        before=mention.before,
        after=mention.after,
        sentence=mention.sentence,
        decimals=mention.decimals,
        significant_decimals=mention.significant_decimals,
        range_low=low,
        range_high=high,
        date_value=mention.date_value,
        notation=mention.notation,
    )


def numeric_tokens(text: str) -> set[float]:
    """Every plain number in a short text, for the prompt-echo exemption."""
    return {
        float(match.group("digits").replace(",", ""))
        for match in _TOKEN.finditer(text)
        if match.group("num")
    }


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Grounding:
    """One number's verdict against the bundle."""

    grounded: bool
    unknown: bool = False
    matched: float | None = None
    tolerance: float | None = None
    why: str = ""


def _candidates(mention: Mention) -> list[tuple[float, float]]:
    """``(value, tolerance)`` pairs to try, in the mention's own unit and in SI.

    A class that fails its own tolerance may still ground through another
    class (rubric §4.2.1): distances are entered as km in the answer and stored
    as metres in the snapshot, so both representations are tried.
    """
    if mention.value is None:
        return []
    value = mention.value
    kind = mention.kind
    if kind == "percent":
        return [(value, 1.0)]
    if kind == "ratio":
        return [(value, 0.05)]
    if kind == "load":
        return [(value, max(0.5, abs(value) * 0.01))]
    if kind == "pace":
        return [(value, float(config.GROUNDING_PACE_TOLERANCE_S))]
    if kind == "duration":
        return [
            (value, float(config.GROUNDING_DURATION_TOLERANCE_S)),
            (value / 60.0, config.GROUNDING_DURATION_TOLERANCE_S / 60.0),
            (value / 3600.0, config.GROUNDING_DURATION_TOLERANCE_S / 3600.0),
        ]
    if kind == "distance":
        pairs = [(value, 0.1)]
        if mention.unit == "km":
            pairs.append((value * 1000, config.GROUNDING_DISTANCE_TOLERANCE_M))
        elif mention.unit == "m":
            pairs.append((value / 1000, 0.1))
        return pairs
    if kind == "prediction":
        tolerance = max(abs(value) * 0.01, config.GROUNDING_ROUNDING_ALLOWANCE_S)
        # "around 42-44 minutes" is a legal estimate of a 42:34 prediction
        # (rubric §10.1), so a prediction rounded to the minute grounds it.
        if mention.decimals == 0 and (mention.unit in {"min", None}):
            tolerance += config.GROUNDING_ROUNDING_ALLOWANCE_S
        return [(value, tolerance)]
    if kind == "count":
        return [(value, 0.0)]
    if kind == "scale":
        return [(value, 0.5)]
    if kind == "year":
        return []
    return [(value, max(0.5, abs(value) * 0.01))]


def _within(value: float, evidence: Sequence[float], tolerance: float) -> float | None:
    best: float | None = None
    best_distance = tolerance
    for candidate in evidence:
        distance = abs(candidate - value)
        if distance <= best_distance:
            best_distance = distance
            best = candidate
    return best


def ground(
    mention: Mention,
    evidence: "Evidence",
    *,
    extra_values: Iterable[float] = (),
    prompt_values: Iterable[float] = (),
) -> Grounding:
    """Decide whether one number is supported by the bundle.

    ``extra_values`` are the rubric's declared constants and the prompt's own
    numbers (a restated question is not a fabrication). ``unknown`` is reserved
    for the preview case: the bundle is incomplete, so absence is not evidence
    of invention.
    """
    if mention.kind == "scale":
        return Grounding(grounded=True, why="scale reference")
    if mention.kind == "date":
        return _ground_date(mention, evidence)
    if mention.value is None:
        return Grounding(grounded=False, why="unparseable")

    pool = list(evidence.values) + list(extra_values) + list(prompt_values)
    for value, tolerance in _candidates(mention):
        matched = _within(value, pool, tolerance)
        if matched is not None:
            return Grounding(grounded=True, matched=matched, tolerance=tolerance)
        if mention.range_low is not None and mention.range_high is not None:
            low = mention.range_low - tolerance
            high = mention.range_high + tolerance
            inside = [candidate for candidate in pool if low <= candidate <= high]
            if inside:
                return Grounding(
                    grounded=True,
                    matched=inside[0],
                    tolerance=tolerance,
                    why="inside the stated range",
                )
    if evidence.scope == "preview":
        return Grounding(
            grounded=False,
            unknown=True,
            why="not found; a tool preview may hide it",
        )
    return Grounding(grounded=False, why="not found in the evidence bundle")


def _ground_date(mention: Mention, evidence: "Evidence") -> Grounding:
    if mention.date_value is None:
        return Grounding(grounded=False, why="unparseable date")
    for candidate in evidence.dates:
        same_year = candidate.year == mention.date_value.year
        if mention.date_value.year == 2000:
            same_year = True
        if (
            candidate.month == mention.date_value.month
            and candidate.day == mention.date_value.day
            and same_year
        ):
            return Grounding(grounded=True, why="date present")
    if evidence.scope == "preview":
        return Grounding(grounded=False, unknown=True, why="date may be in a preview")
    return Grounding(grounded=False, why="date not present")


# ---------------------------------------------------------------------------
# Evidence bundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Evidence:
    """Everything a model was allowed to know, flattened into numbers and dates."""

    values: tuple[float, ...]
    dates: tuple[date, ...]
    scope: str
    previews: int
    truncated_previews: int
    sources: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        """True when every tool result was available in full."""
        return self.scope == "full"


def _walk_numbers(payload: object, sink: set[float], dates: set[date]) -> None:
    if isinstance(payload, bool):
        return
    if isinstance(payload, (int, float)):
        sink.add(float(payload))
        return
    if isinstance(payload, str):
        if _ISO_DATE.fullmatch(payload):
            try:
                dates.add(date.fromisoformat(payload))
            except ValueError:
                pass
        for match in _TOKEN.finditer(payload):
            if match.group("num"):
                sink.add(float(match.group("digits").replace(",", "")))
            elif match.group("iso"):
                try:
                    dates.add(date.fromisoformat(match.group("iso")))
                except ValueError:
                    pass
        return
    if isinstance(payload, Mapping):
        for value in payload.values():
            _walk_numbers(value, sink, dates)
        return
    if isinstance(payload, (list, tuple)):
        for value in payload:
            _walk_numbers(value, sink, dates)


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _walk_preview(text: str, sink: set[float], dates: set[date]) -> None:
    """Fall back to text scanning when a preview is not valid JSON."""
    _walk_numbers(text, sink, dates)


def _raw_path(raw_dir: Path | None, record: Mapping[str, object]) -> Path | None:
    if raw_dir is None:
        return None
    record_id = record.get("record_id")
    if not record_id:
        return None
    path = raw_dir / f"{record_id}.jsonl"
    return path if path.exists() else None


def _walk_raw(path: Path, sink: set[float], dates: set[date]) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            _walk_preview(line, sink, dates)
            continue
        if isinstance(payload, Mapping) and "result" in payload:
            _walk_numbers(payload["result"], sink, dates)
        else:
            _walk_numbers(payload, sink, dates)


def build_evidence(
    record: Mapping[str, object],
    fixture: object,
    raw_dir: Path | None = None,
) -> Evidence:
    """Collect the numbers and dates the model may legitimately have seen."""
    values: set[float] = set()
    dates: set[date] = set()
    sources: list[str] = ["snapshot"]
    snapshot = getattr(fixture, "snapshot", None)
    if snapshot is not None:
        _walk_numbers(snapshot, values, dates)

    calls = record.get("tool_calls") or []
    truncated = 0
    raw_path = _raw_path(raw_dir, record)
    if raw_path is not None:
        _walk_raw(raw_path, values, dates)
        sources.append("raw")
    for call in calls:
        if not isinstance(call, Mapping):
            continue
        preview = str(call.get("result_preview") or "")
        at_cap = len(preview) >= config.BENCH_PREVIEW_CHARS
        if at_cap:
            truncated += 1
        if raw_path is not None:
            continue
        sources.append(f"tool:{call.get('name') or '?'}")
        try:
            _walk_numbers(json.loads(preview), values, dates)
        except ValueError:
            _walk_preview(preview, values, dates)

    scope = "preview" if truncated and raw_path is None else "full"
    return Evidence(
        values=tuple(sorted(values)),
        dates=tuple(sorted(dates)),
        scope=scope,
        previews=len(calls),
        truncated_previews=truncated,
        sources=tuple(dict.fromkeys(sources)),
    )


@dataclass(frozen=True)
class Visible:
    """What of the snapshot actually reached the model.

    A rule that requires the model to mention a fact must not fire when the
    payload was truncated before that fact. The check is textual because the
    production serialiser is the authority on the cut point, and re-deriving it
    from the dict would be a second implementation that can drift.
    """

    truncated: bool
    prefix: str
    max_chars: int = 0

    def contains(self, fragment: str) -> bool:
        """True when the fragment is in the part of the payload that was sent."""
        if not self.truncated:
            return True
        return fragment in self.prefix

    def has_json(self, key: str, value: object) -> bool:
        """True when ``key`` is present with ``value`` in the sent prefix."""
        if not self.truncated:
            return True
        return f'"{key}":{json.dumps(value, separators=(",", ":"))}' in self.prefix


def visibility(record: Mapping[str, object], fixture: object) -> Visible:
    """Compute which snapshot facts reached the model for this record."""
    context = record.get("context") or {}
    truncated = bool(context.get("truncated"))
    if not truncated:
        return Visible(truncated=False, prefix="")
    from app import coach_llm

    snapshot = getattr(fixture, "snapshot", {}) or {}
    payload, was_truncated = coach_llm.snapshot_payload(dict(snapshot))
    return Visible(
        truncated=was_truncated,
        prefix=payload,
        max_chars=len(payload),
    )


# ---------------------------------------------------------------------------
# Self-computed numbers (G-02)
# ---------------------------------------------------------------------------

_ARITHMETIC = re.compile(
    r"(?<![\d.])"
    r"(?P<left>\d+(?:[.,]\d+)?)"
    r"(?P<op>\s*[+\-−*=]\s*|\s+(?:minus|plus|times|divided by)\s+)"
    r"(?P<right>\d+(?:[.,]\d+)?)"
    r"(?![\d.])",
    re.IGNORECASE,
)

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_FRACTION = re.compile(r"\d{1,3}/\d{1,2}(?:/\d{1,2})?")

# A conversion needs a number next to the unit: "6.1 miles" converts, while
# "400 m / 1 km / 1 mile" is a list of best-effort labels.
_CONVERSION = re.compile(
    r"\b\d+\.\d+\s*(miles|mile|feet|metres|meters)\b|"
    r"\b\d+\s*(km/h|mph|kilometres per hour|kilometers per hour)\b|"
    r"\b(converted to|in miles|in kilometres)\b",
    re.IGNORECASE,
)

_AVERAGE_PROSE = re.compile(
    r"\b(average of|averaged|sum of|combined total|total of|difference between|"
    r"half of|twice|double|a rise of|an increase of|"
    r"a decrease of|a drop of|a reduction of)\b",
    re.IGNORECASE,
)

_METRIC_WORD = re.compile(
    r"\b(load|ctl|atl|tsb|vo2\s?max|vdot|pace|distance|volume|intensity|"
    r"ratio|percent|percentage|minutes|kilometres|kilometers|km|weekly)\b",
    re.IGNORECASE,
)

_NX = re.compile(r"(?<![\w.])(?P<value>\d+(?:\.\d+)?)\s*[x×](?![\w])", re.IGNORECASE)

# "the easy share is ~9 points above target" is a subtraction the model did;
# the pre-computed fact states the share itself, not the gap.
_DELTA_PROSE = re.compile(
    r"(?<![\w.])(?P<value>\d+(?:\.\d+)?)\s*(?:%|percent(?:age)?\s+points?|"
    r"points?|units?)\s+(?:points?\s+)?(above|below|over|under|higher|lower|"
    r"more|less|off)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DerivedClaim:
    """A number the answer computed instead of quoting.

    ``scope`` is ``"span"`` when only the operator expression is derived (a sum
    written out, ``24+20``) and ``"sentence"`` when the whole sentence is a
    computation (an average, a conversion, a target). The distinction lets G-01
    ignore exactly the numbers G-02 already charges, instead of charging twice.
    """

    text: str
    reason: str
    start: int
    end: int
    scope: str = "span"


def arithmetic_claims(
    text: str, evidence: Evidence, *, prompt_values: Iterable[float] = ()
) -> list[DerivedClaim]:
    """Find explicit arithmetic, unit conversions and invented multipliers.

    Deliberately conservative. A benchmark that guesses at implicit arithmetic
    would fail good answers for saying "8 km left"; only a visible operator, a
    named arithmetic verb, a unit conversion, a stated target or an ``Nx``
    multiplier that is not pre-computed counts. Silent wrong arithmetic is
    caught by G-01.

    Dates, ``80/10/10`` notation and session formats (``6x400``, ``90/90``) are
    excluded: they are not computations, and a grounding rule that fires on
    them would punish every well-formed answer.
    """
    claims: list[DerivedClaim] = []
    known = set(evidence.values) | set(prompt_values)
    date_spans = [(match.start(), match.end()) for match in _ISO_DATE.finditer(text)]
    fraction_spans = [
        (match.start(), match.end())
        for match in _FRACTION.finditer(text)
        if _is_notation(match.group(0))
    ]

    def excluded(start: int, end: int) -> bool:
        if any(low <= start < high or low < end <= high for low, high in date_spans):
            return True
        return any(
            low <= start < high or low < end <= high for low, high in fraction_spans
        )

    for match in _ARITHMETIC.finditer(text):
        operator = match.group("op").strip()
        if excluded(match.start(), match.end()):
            continue
        if operator in {"-", "−"} and not match.group("op").startswith(" "):
            # "42-44" is a range, not a subtraction; a subtraction is spaced.
            continue
        claims.append(
            DerivedClaim(
                text=match.group(0).strip(),
                reason="explicit arithmetic",
                start=match.start(),
                end=match.end(),
            )
        )

    for pattern, reason in (
        (_AVERAGE_PROSE, "self-computed metric"),
        (_CONVERSION, "unit conversion beyond h:mm:ss"),
    ):
        for match in pattern.finditer(text):
            sentence = _sentence_at(text, match.start(), match.end())
            if pattern is _CONVERSION and not re.search(r"\d", sentence):
                continue
            if pattern is _AVERAGE_PROSE:
                if not _METRIC_WORD.search(sentence):
                    continue
                offset = text.find(sentence)
                nearby = [
                    mention.value
                    for mention in _naive_numbers(sentence)
                    if mention.value is not None
                    and 0 <= mention.start + offset - match.end() <= 40
                ]
                if nearby and any(value in known for value in nearby):
                    continue
            claims.append(
                DerivedClaim(
                    text=sentence,
                    reason=f"{reason} ({match.group(0).strip().lower()})",
                    start=match.start(),
                    end=match.end(),
                    scope="sentence",
                )
            )

    for match in _DELTA_PROSE.finditer(text):
        value = float(match.group("value"))
        if value in known:
            continue
        sentence = _sentence_at(text, match.start(), match.end())
        claims.append(
            DerivedClaim(
                text=sentence,
                reason="delta computed by the answer",
                start=match.start(),
                end=match.end(),
                scope="sentence",
            )
        )

    session_multiplier = re.compile(
        r"\d+\s*[×x]\s*\d+\s*(s|sec|secs|seconds|min|mins|minutes|m|km|"
        r"reps?|strides?|sets?)\b",
        re.IGNORECASE,
    )
    for match in _NX.finditer(text):
        value = float(match.group("value"))
        if value in known:
            continue
        sentence = _sentence_at(text, match.start(), match.end())
        if session_multiplier.search(sentence):
            # "4-6 x 20 s strides" is a session format, not a multiplier claim.
            continue
        if _METRIC_WORD.search(sentence) or _LOAD_CONTEXT.search(sentence):
            claims.append(
                DerivedClaim(
                    text=sentence,
                    reason="multiplier not pre-computed",
                    start=match.start(),
                    end=match.end(),
                    scope="sentence",
                )
            )
    return _dedupe(claims)


def _naive_numbers(text: str) -> list[Mention]:
    """Numbers without the arithmetic pass, for the "is it pre-computed" test."""
    return extract_numbers(text)


def _is_notation(token: str) -> bool:
    """True for ``80/10/10``, ``90/90``, ``10/24``: parts are all small integers.

    A slash whose parts are all at most 100 is notation (a distribution, an
    exercise name, a date); ``960/600`` is a division and stays a computation.
    """
    parts = re.findall(r"\d+(?:\.\d+)?", token)
    if len(parts) < 2:
        return False
    try:
        return all(float(part) <= 100 for part in parts)
    except ValueError:
        return False


def _sentence_of_claim(claim: DerivedClaim, text: str) -> tuple[int, int]:
    if claim.scope == "sentence":
        return _sentence_bounds(text, claim.start, claim.end)
    return (claim.start, claim.end)


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    left = max(
        text.rfind("\n", 0, start),
        text.rfind(". ", 0, start),
        text.rfind("! ", 0, start),
        text.rfind("? ", 0, start),
    )
    right_candidates = [
        index
        for index in (
            text.find("\n", end),
            text.find(". ", end),
            text.find("! ", end),
            text.find("? ", end),
        )
        if index != -1
    ]
    right = min(right_candidates) if right_candidates else len(text)
    return (left + 1, right + 1)


def _dedupe(claims: Sequence[DerivedClaim]) -> list[DerivedClaim]:
    seen: set[tuple[int, str]] = set()
    unique: list[DerivedClaim] = []
    for claim in claims:
        key = (claim.start, claim.reason)
        if key in seen:
            continue
        seen.add(key)
        unique.append(claim)
    return unique


def iter_numbers(payload: object) -> Iterator[float]:
    """Yield every number in a JSON-shaped payload, for tests and diagnostics."""
    sink: set[float] = set()
    _walk_numbers(payload, sink, set())
    yield from sorted(sink)
