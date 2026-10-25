"""What an exercise loads, and which muscles a pain location maps onto.

This is a small, explicit keyword table rather than a model. The point is to be
**explainable**: every classification returns the keyword that matched, so the
UI can say *why* a leg press counted as a quadriceps exercise instead of asking
the athlete to trust a black box.

Vocabulary follows `GLOSSARY.md` and `SESSION_BODY_AREAS` /
`FEEDBACK_PAIN_LOCATIONS` in `app/config.py`.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

# Order matters: the first keyword found for a muscle group wins, and longer,
# more specific keywords are listed before the generic ones they contain.
# ("leg curl" before "curl"; "leg press" before "press".)
EXERCISE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # ----- lower body: quadriceps -----
    ("leg extension", ("quads",)),
    ("leg press", ("quads", "glutes")),
    ("hack squat", ("quads", "glutes")),
    ("bulgarian", ("quads", "glutes")),
    ("split squat", ("quads", "glutes")),
    ("step up", ("quads", "glutes")),
    ("step-up", ("quads", "glutes")),
    ("lunge", ("quads", "glutes")),
    ("squat", ("quads", "glutes", "back")),
    ("wall sit", ("quads",)),
    # ----- lower body: hamstrings / glutes -----
    ("romanian deadlift", ("hamstrings", "glutes")),
    ("stiff leg deadlift", ("hamstrings",)),
    ("deadlift", ("hamstrings", "glutes", "back")),
    ("leg curl", ("hamstrings",)),
    ("nordic", ("hamstrings",)),
    ("good morning", ("hamstrings", "back")),
    ("hip thrust", ("glutes", "hamstrings")),
    ("glute bridge", ("glutes",)),
    ("kickback", ("glutes",)),
    ("abduction", ("abductors", "glutes")),
    ("adduction", ("adductors",)),
    ("clamshell", ("abductors", "glutes")),
    # ----- lower body: calf / achilles / foot -----
    ("calf raise", ("calves", "achilles")),
    ("heel raise", ("calves", "achilles")),
    ("calf stretch", ("calves",)),
    ("ankle", ("ankle", "calves")),
    ("toe raise", ("shin", "ankle")),
    # ----- hip -----
    ("hip flexor", ("hip_flexors", "hip")),
    ("psoas", ("hip_flexors", "hip")),
    ("hip mobility", ("hip", "hip_flexors")),
    ("90/90", ("hip",)),
    # ----- core / back -----
    ("plank", ("core",)),
    ("crunch", ("core",)),
    ("hollow", ("core",)),
    ("dead bug", ("core",)),
    ("bird dog", ("core", "back")),
    ("oblique", ("obliques",)),
    ("side bend", ("obliques",)),
    ("back extension", ("back",)),
    ("superman", ("back",)),
    # ----- upper body -----
    ("row", ("lats", "back", "biceps")),
    ("pull up", ("lats", "biceps")),
    ("pull-up", ("lats", "biceps")),
    ("pulldown", ("lats", "biceps")),
    ("bench", ("chest", "triceps", "shoulders")),
    ("push up", ("chest", "triceps")),
    ("push-up", ("chest", "triceps")),
    ("chest fly", ("chest",)),
    ("overhead press", ("shoulders", "triceps")),
    ("shoulder press", ("shoulders", "triceps")),
    ("lateral raise", ("shoulders",)),
    ("front raise", ("shoulders",)),
    ("face pull", ("shoulders", "back")),
    ("biceps", ("biceps",)),
    ("triceps", ("triceps",)),
    ("curl", ("biceps",)),
    ("wrist", ("forearms",)),
    ("neck", ("neck",)),
    # ----- stretching / mobility -----
    ("hamstring stretch", ("hamstrings",)),
    ("quad stretch", ("quads",)),
    ("glute stretch", ("glutes",)),
    ("hip stretch", ("hip",)),
)

# Muscles that can plausibly contribute to each reported pain location.
PAIN_TO_MUSCLES: dict[str, tuple[str, ...]] = {
    "knee": ("quads", "hamstrings", "glutes"),
    "shin": ("calves", "shin"),
    "calf": ("calves",),
    "achilles": ("achilles", "calves"),
    "foot": ("foot", "calves"),
    "ankle": ("ankle", "calves"),
    "hip": ("hip", "hip_flexors", "glutes", "adductors"),
    "hamstring": ("hamstrings",),
    "quad": ("quads",),
    "back": ("back", "core"),
    "other": (),
}

# Pain locations the correlation engine will try to explain. Anything else is
# reported as "no plausible link" rather than guessed at.
LOWER_LIMB_PAIN = frozenset(
    {"knee", "shin", "calf", "achilles", "foot", "ankle", "hip", "hamstring", "quad"}
)


def _normalise(text: str) -> str:
    """Lower-case, strip accents and collapse punctuation to spaces."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", plain.lower()).strip()


def classify_exercise(name: str) -> dict:
    """Return the muscle groups an exercise name loads, and why.

    The **first** matching keyword wins, and the table is ordered so that the
    most specific movement comes first: "leg curl" is a hamstring exercise and
    must never also be read as a biceps curl. ``matched`` names the keyword that
    fired, so a UI can explain the classification. An unknown exercise returns
    empty lists rather than a guessed group.
    """
    text = _normalise(name)
    for keyword, groups in EXERCISE_KEYWORDS:
        if _normalise(keyword) in text:
            return {
                "name": name,
                "muscles": [g for g in groups if g],
                "matched": [keyword],
            }
    return {"name": name, "muscles": [], "matched": []}


def muscles_for_pain(location: str) -> tuple[str, ...]:
    """Muscle groups that could plausibly explain a pain location."""
    return PAIN_TO_MUSCLES.get((location or "").strip().lower(), ())


def exercises_loading(muscles: Iterable[str], exercises: Iterable[dict]) -> list[dict]:
    """Exercises from a session that load any of the given muscle groups."""
    wanted = {m for m in muscles if m}
    if not wanted:
        return []
    hits = []
    for exercise in exercises:
        info = classify_exercise(exercise.get("name", ""))
        overlap = [m for m in info["muscles"] if m in wanted]
        if overlap:
            hits.append(
                {
                    "name": exercise.get("name", ""),
                    "muscles": overlap,
                    "matched": info["matched"],
                }
            )
    return hits
