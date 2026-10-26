"""When two readings of a field are ONE value (order 223).

The same number, unit and gauge/absolute basis is one value when the only text
around it is a plain note: "340 psig" and "340 psig (By Contractor, as per
Code)", "9400 Kg/hr Note - 2". ANYTHING else around the number may change what
it means, so the two readings stay two values for the engineer: a condition
("at 20 C", "for liquid service"), a bound ("max", "min"), a negation, a side
or a state ("shell side", "cold"), another quantity ("(23 bar)"), a sign, a
provisional marker ("TBC", "estimated", "typical"). A wrongly split value costs
an engineer a look; a wrongly merged one hides a conflict.

So this is an ALLOW-list (order 223 review): the text around the printed number
must be made only of the neutral words below, a reference to a code ("per ASME
VIII") and digits (note numbers). Every other word keeps the readings apart.

The number-and-unit key is `rule_eval.same_value_key` (shared with the rule
step).
"""

from __future__ import annotations

import re

from .rule_eval import same_value_key

#: Words that make a note a plain note. Deliberately short and closed: the
#: authors of a note (who owes the value), a pointer to a note or a code, and
#: the words of the datasheet's own furniture. Nothing here states a condition,
#: a bound, a state or a degree of certainty.
NEUTRAL_WORDS = frozenset(
    {
        "by", "vendor", "contractor", "supplier", "others",
        "as", "per", "code", "standard",
        "note", "notes", "see", "ref", "refer", "reference", "to",
        "the", "data", "sheet", "datasheet",
    }
)  # fmt: skip

#: "per ASME VIII", "per API 520": a reference to a code, not a rate or a
#: condition. Upper-case designators only; "per 100 m" and "per hour" are not.
_CODE_REFERENCE = re.compile(
    r"\bper\s+(?:[A-Z]{2,}\b[\s.\-]*(?:[IVXLC]+\b|\d[\d.\-]*)?)+"
)
#: Characters that state a degree, a relation or a sign.
_SYMBOLS = re.compile(r"[@%°±~<>=+*/]")
#: A sign glued to a number: "(-10)", " -10". A spaced dash ("Note - 2") is not one.
_SIGNED = re.compile(r"(?:^|[\s(\[])[-\u2212\u2013]\d")


def _around_the_number(fact: dict) -> tuple[str, str] | None:
    """(text before the printed number, text after its unit), or None when the
    number cannot be found as written (then the whole text is the cautious key)."""
    text = " ".join(str(fact.get("field_value") or "").split())
    raw_value = str(fact.get("raw_value") or "").strip()
    unit = str(fact.get("raw_unit") or "").strip()
    at = text.lower().find(raw_value.lower()) if raw_value else -1
    if at < 0:
        return None
    rest = text[at + len(raw_value) :].lstrip()
    if unit and rest.lower().startswith(unit.lower()):
        rest = rest[len(unit) :]
    return text[:at], rest


def _plain_note(before: str, after: str) -> bool:
    """True when nothing around the number changes its meaning."""
    if re.sub(r"[\s(\[{]", "", before):  # "not 340", "- 340", "approx. 340"
        return False
    after = _CODE_REFERENCE.sub(" ", after)
    if _SYMBOLS.search(after) or _SIGNED.search(after):
        return False
    return all(word in NEUTRAL_WORDS for word in re.findall(r"[a-z]+", after.lower()))


def key(fact: dict) -> tuple:
    """Two facts with the same key are one value."""
    base = same_value_key(fact)
    if base[0] == "t":
        return base  # text values are already compared as text
    around = _around_the_number(fact)
    if around is not None and _plain_note(*around):
        return base
    text = " ".join(str(fact.get("field_value") or "").lower().split())
    return (*base, text)
