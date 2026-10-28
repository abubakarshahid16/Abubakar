"""Order 264.8: a Part's construction is settled by a fact the datasheet STATES.

A standard's Part or appendix whose own scope limits it to a construction ("carbon and low alloy
steel", "welded construction") was held for the engineer whenever the model could not tie it to the
sheet: 2,441 of 4,790 applicable vessel requirements waited on 27 such questions. The sheet usually
states the construction: a shell material, a welding note. `settle` reads the closed, DRAFT list in
`reference/construction_facts.json`: a family is named by the words the Part's construction phrase
uses; it is settled when a stated fact (its label and value) matches the family's patterns, in one of
the family's fields. Only "applies" is decided here, with the fact and its page as evidence; a Part
is never excluded here, and a layer on a base (cladding, a lining) never settles. Anything else
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


@functools.lru_cache(maxsize=4)
def _families(path: str, mtime: float) -> tuple:
    del mtime
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(
        {
            "name": f["name"],
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


def settle(
    construction: str, facts: list[dict], *, path: Path | None = None
) -> dict | None:
    """{"answer": "applies", "family", "field", "value", "page", "fact_id"} when a stated fact settles that
    the equipment is of the construction the Part is limited to, else None (the model, then the
    engineer, decide as before)."""
    from . import datasheet_checks
    from .datasheets import normalise_field_name

    rules = datasheet_checks.load_rules()
    named = [f for f in families(path) if _names(construction, f)]
    if not named:
        return None
    for family in named:
        for fact in facts:
            value = str(fact.get("field_value") or fact.get("raw_value") or "").strip()
            if fact.get("is_blank") or not value:
                continue
            label = fact.get("field_label") or fact.get("field_name") or ""
            if family["roles"] is not None:
                role = datasheet_checks.role_of(normalise_field_name(label), rules)
                if role not in family["roles"]:
                    continue
            text = f"{label} {value}".lower()
            if _LAYER.search(value.lower()):
                continue
            if any(p.search(text) for p in family["patterns"]):
                return {
                    "answer": "applies",
                    "family": family["name"],
                    "field": label,
                    "value": value,
                    "page": fact.get("page"),
                    "fact_id": fact.get("id"),
                }
    return None
