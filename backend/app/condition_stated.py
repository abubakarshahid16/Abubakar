"""#899 (PF2): a condition the sheet STATES is checked; one it plainly rules out is excused.

`conditions.evaluate` answers UNKNOWN ("an engineer decides") when the condition's
words are not a vocabulary term it knows. That is safe and it is also a miss: a
sheet that says "Valve type: Conventional" does establish "a conventional valve",
and a sheet that says "Internal lining: None" does rule out "where an internal
lining is specified". PF1 planted a defect behind exactly such a condition and the
review sent it to the engineer instead of checking it.

Two general rules, each read from the condition's own words and the field's own
name; no standard, material, service or label is named here. They only REFINE an
UNKNOWN: a definite answer from the reader or the term gate is never changed.

  S  STATED QUALIFIER. The condition is "<qualifier> <equipment>" ("a conventional
     valve"). A trusted field whose NAME names that equipment and whose VALUE says
     the qualifier (every qualifier word, whole words) establishes the condition.
     Negation anywhere in the condition or in the value ("non-conventional",
     "not conventional") establishes nothing. This rule never excuses a clause:
     a different qualifier in the value is not proof of anything here.
  P  PRESENCE. The condition is "<thing> is specified / provided / required /
     used ..." ("an internal lining is specified"). A trusted field named for that
     thing alone (its name holds the thing's words and at most a word such as
     "required" or "type") that states a value establishes it; the same field
     stating "none", "no" or "not required" rules it out. A field about some
     other aspect of the thing ("lining holiday test: none") says nothing about
     whether the thing is there. Placeholders (N/A, TBD) and conflicting fields
     decide nothing.

Pure functions; `conditions` passes in what it owns (its folding, empty values and
trust test) so there is no import cycle and no second copy of those rules.
"""

from __future__ import annotations

import re
from collections.abc import Callable

_TOKEN = re.compile(r"[a-z0-9][a-z0-9.\-/]*")

#: Words that only join a condition together.
_JOINERS = frozenset(
    {
        "a",
        "an",
        "the",
        "for",
        "where",
        "when",
        "if",
        "in",
        "on",
        "of",
        "with",
        "any",
        "all",
        "each",
        "that",
        "which",
        "is",
        "are",
        "be",
    }
)
#: A negation anywhere makes a stated word mean nothing for the condition.
_NEGATION = frozenset(
    {
        "not",
        "no",
        "non",
        "without",
        "other",
        "than",
        "except",
        "excluding",
        "unless",
        "neither",
        "nor",
    }
)
#: Words a field name may add to the thing it is named for and still be "the
#: field that says whether the thing is there".
_NAME_ALLOWED = frozenset(
    {
        "required",
        "specified",
        "provided",
        "type",
        "fitted",
        "installed",
        "used",
        "applied",
        "supplied",
        "included",
        "present",
        "yes",
        "no",
    }
)
_PRESENCE = re.compile(
    r"^(?:(?:where|if|when|for)\s+)?(?:(?:an?|the|any)\s+)?(?P<thing>[a-z][a-z \-]*?)\s+"
    r"(?:is|are)\s+(?:specified|provided|required|used|installed|fitted|applied|supplied|"
    r"included|present)\s*$"
)
_ABSENT = frozenset(
    {
        "none",
        "no",
        "nil",
        "not required",
        "not provided",
        "not fitted",
        "not installed",
        "not used",
        "not supplied",
    }
)


def _words(text: str) -> list[str]:
    return _TOKEN.findall(text)


def _has_all(words: list[str], wanted: list[str]) -> bool:
    return all(w in words for w in wanted)


def _negated(words: list[str]) -> bool:
    return any(w in _NEGATION or w.startswith("non-") for w in words)


def _value(fact: dict) -> str:
    return " ".join(_words(str(fact.get("field_value") or "").lower()))


#: A value that says there is no such thing: "none", "none required", "unlined", "absent", "no lining".
#: "No. 2 rubber" and "No 4 grade" are names, not a "no" (a digit follows).
_ABSENT_FIRST = frozenset({"none", "nil", "unlined", "absent", "without"})
#: A value that is not a statement yet: nothing is decided on it, either way.
_UNSTATED_START = (
    "not specified",
    "not provided by",
    "not yet",
    "to be ",
    "by vendor",
    "vendor to",
    "unknown",
    "not known",
    "pending",
    "tba",
    "tbc",
    "tbd",
    "see ",
)
#: A value that offers a choice or is unconfirmed does not settle which one the equipment is.
_UNCERTAIN = frozenset(
    {
        "or",
        "and",
        "either",
        "option",
        "optional",
        "options",
        "alternative",
        "tbc",
        "tbd",
        "tba",
        "to",
        "be",
        "confirmed",
        "confirm",
        "proposed",
        "pending",
        "subject",
        "unless",
    }
)


def _absent(value: str) -> bool:
    if value in _ABSENT:
        return True
    first, _, rest = value.partition(" ")
    if first in _ABSENT_FIRST:
        return True
    return first == "no" and bool(rest) and not rest[0].isdigit()


def _unstated(value: str) -> bool:
    return value.startswith(_UNSTATED_START)


def _offers_a_choice(raw: str, words: list[str]) -> bool:
    return (
        any(w in _UNCERTAIN for w in words)
        or re.search(r"\w\s*[/&]\s*\w", raw) is not None
    )


def _decision(
    state: str,
    shape: str,
    condition: str,
    reason: str,
    fact: dict,
    evidence: Callable[[dict], dict],
) -> dict:
    return {
        "state": state,
        "shape": shape,
        "condition": condition,
        "reason": reason,
        "evidence": evidence(fact),
    }


def _stated_qualifier(
    condition: str,
    facts: list[dict],
    equipment: tuple[str, ...],
    evidence: Callable[[dict], dict],
) -> dict | None:
    words = _words(condition)
    if _negated(words):
        return None
    terms = [t for t in equipment if _has_all(words, _words(t))]
    if not terms:
        return None
    named = {w for t in terms for w in _words(t)}
    qualifiers = [w for w in words if w not in _JOINERS and w not in named]
    if not qualifiers:
        return None
    for fact in facts:
        name, value = (
            _words(str(fact.get("field_name") or "").lower()),
            _words(str(fact.get("field_value") or "").lower()),
        )
        raw = str(fact.get("field_value") or "").lower()
        if (
            _negated(value)
            or _offers_a_choice(raw, value)
            or not any(_has_all(name, _words(t)) for t in terms)
        ):
            continue
        if _has_all(value, qualifiers):
            return _decision(
                "SATISFIED",
                "stated_qualifier",
                condition,
                f"{fact.get('field_name')!r} states {fact.get('field_value')!r}",
                fact,
                evidence,
            )
    return None


def _presence(
    condition: str,
    facts: list[dict],
    evidence: Callable[[dict], dict],
    is_empty: Callable[[str | None], bool],
) -> dict | None:
    found = _PRESENCE.match(condition)
    if not found:
        return None
    thing = [w for w in _words(found.group("thing")) if w not in _JOINERS]
    if not thing or len(thing[-1]) < 4:
        return None
    present: list[dict] = []
    absent: list[dict] = []
    for fact in facts:
        name = _words(str(fact.get("field_name") or "").lower())
        if not _has_all(name, thing) and thing[-1] not in name:
            continue
        if any(w not in thing and w not in _NAME_ALLOWED for w in name):
            continue
        value = _value(fact)
        if _absent(value):
            absent.append(fact)
        elif not is_empty(value) and not _unstated(value):
            present.append(fact)
    if (present and absent) or not (present or absent):
        return None
    fact = (absent or present)[0]
    if absent:
        return _decision(
            "NOT_SATISFIED",
            "presence",
            condition,
            f"{fact.get('field_name')!r} states {fact.get('field_value')!r}, so "
            f"{' '.join(thing)!r} is not there",
            fact,
            evidence,
        )
    return _decision(
        "SATISFIED",
        "presence",
        condition,
        f"{fact.get('field_name')!r} states {fact.get('field_value')!r}",
        fact,
        evidence,
    )


def refine(
    result: dict | None,
    facts: list[dict] | None,
    *,
    equipment: tuple[str, ...],
    evidence: Callable[[dict], dict],
    is_empty: Callable[[str | None], bool],
    low_trust: Callable[[dict], str | None],
) -> dict | None:
    """`result` unchanged unless it is UNKNOWN and a stated field settles it."""
    if result is None or result["state"] != "UNKNOWN" or not facts:
        return result
    condition = str(result.get("condition") or "").lower()
    stated = [
        f for f in facts if not is_empty(f.get("field_value")) or _absent(_value(f))
    ]
    trusted = [f for f in stated if not low_trust(f)]
    if len(trusted) != len(stated):
        return result  # a low-trust value is not evidence, and its presence may not change the answer
    return (
        _stated_qualifier(condition, trusted, equipment, evidence)
        or _presence(condition, trusted, evidence, is_empty)
        or result
    )
