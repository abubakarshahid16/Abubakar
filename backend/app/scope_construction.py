"""Order 264.8: a Part's construction is settled by a fact the datasheet STATES.

A standard's Part or appendix whose own scope limits it to a construction ("carbon and low alloy
steel", "welded construction") was held for the engineer whenever the model could not tie it to the
sheet: 2,441 of 4,790 applicable vessel requirements waited on 27 such questions. The sheet usually
states the construction: a shell material, a welding note. `settle` reads the closed, DRAFT list in
`reference/construction_facts.json`: a family is named by the words the Part's construction phrase
uses; it is settled when the VALUE of a stated fact (never its label) matches the family's patterns, in one
of the family's fields. Only "applies" is decided here, with the fact and its page as evidence (a fact
with no page settles nothing); a Part is never excluded here. A negated hit ("not welded"), a layer on
a base (cladding, a lining) and a mixed vessel (two material families on the shell and the heads) settle
nothing. Anything else
stays with the model task and then the engineer. No standard or Part is named in code.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

PATH = Path(__file__).parent / "reference" / "construction_facts.json"
#: A layer on a base material does not change what the base is made of.
_LAYER = re.compile(
    r"\b(?:clad\w*|overlay\w*|lin(?:ed|ing)|coat\w*|galvani[sz]\w*|plat(?:ed|ing))\b"
)
_WORD = re.compile(r"[a-z0-9]+")


#: A negation within this many words before a hit: "not welded", "non-forged", "without cladding".
_NEGATIONS = frozenset(
    ["not", "non", "no", "without", "never", "nor", "neither", "except", "excluding"]
)
_NEG_WINDOW = 4


@functools.lru_cache(maxsize=4)
def _families(path: str, mtime: float) -> tuple:
    del mtime
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(
        {
            "name": f["name"],
            "exclusive": f.get("exclusive"),
            "scope_words": [
                frozenset(w.lower() for w in words) for words in f["scope_words"]
            ],
            "roles": None if f.get("roles") is None else frozenset(f["roles"]),
            "patterns": [re.compile(p, re.IGNORECASE) for p in f["patterns"]],
        }
        for f in data["families"]
    )


def families(path: Path | None = None) -> tuple:
    path = path or PATH
    return _families(str(path), path.stat().st_mtime)


def _names(construction: str, family: dict) -> bool:
    """Does the Part's construction phrase use this family's words (every word of one entry)?"""
    stems = _WORD.findall((construction or "").lower())
    return any(
        all(any(s.startswith(word) for s in stems) for word in words)
        for words in family["scope_words"]
    )


def _negated(value: str, start: int) -> bool:
    """Does a negation stand within a few words before the hit that begins at `start`?"""
    before = _WORD.findall(value[:start].lower())[-_NEG_WINDOW:]
    return any(w in _NEGATIONS for w in before)


def _hits(family: dict, fact: dict, rules: dict) -> bool:
    """Does the VALUE of this fact (never its label) state the family, in one of the family's fields,
    with no negation before the hit and no layer on a base?"""
    from . import datasheet_checks
    from .datasheets import normalise_field_name

    value = str(fact.get("field_value") or fact.get("raw_value") or "").strip()
    if (
        fact.get("is_blank")
        or not value
        or fact.get("page") is None
        or _LAYER.search(value.lower())
    ):
        return False  # no claim without a resolving page
    if family["roles"] is not None:
        label = fact.get("field_label") or fact.get("field_name") or ""
        if (
            datasheet_checks.role_of(normalise_field_name(label), rules)
            not in family["roles"]
        ):
            return False
    return any(
        not _negated(value, m.start())
        for pattern in family["patterns"]
        for m in pattern.finditer(value)
    )


def settle(
    construction: str, facts: list[dict], *, path: Path | None = None
) -> dict | None:
    """{"answer": "applies", "family", "field", "value", "page", "fact_id"} when a stated fact settles that
    the equipment is of the construction the Part is limited to, else None (the model, then the
    engineer, decide as before). A material family is never settled when another material family is
    also stated on the shell or the heads, or when one value names two of them: that is a mixed
    vessel, and the engineer decides."""
    from . import datasheet_checks

    rules = datasheet_checks.load_rules()
    every = families(path)
    for family in (f for f in every if _names(construction, f)):
        matching = [fact for fact in facts if _hits(family, fact, rules)]
        if not matching:
            continue
        if family["exclusive"]:
            rivals = [
                f
                for f in every
                if f["exclusive"] == family["exclusive"] and f is not family
            ]
            if any(_hits(r, fact, rules) for r in rivals for fact in facts):
                continue
        fact = matching[0]
        return {
            "answer": "applies",
            "family": family["name"],
            "field": fact.get("field_label") or fact.get("field_name"),
            "value": str(fact.get("field_value") or fact.get("raw_value")).strip(),
            "page": fact.get("page"),
            "fact_id": fact.get("id"),
        }
    return None
