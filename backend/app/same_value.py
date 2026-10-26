"""When two readings of a field are ONE value (order 223).

The same number, unit and gauge/absolute basis is one value even when a note
follows it ("340 psig" and "340 psig (By Contractor, as per Code)"). But a note
that changes what the number means is not a note: "340 psig at 20 C" and
"340 psig at 120 C", "340 (max)" and "340 (min)", "not 340" are different
statements, so they stay two values for the engineer.

The number-and-unit key is `rule_eval.same_value_key` (shared with the rule
step). Here the text around the printed number is checked for a qualifier.
"""

from __future__ import annotations

import re

from .rule_eval import same_value_key

#: Words and shapes that make the text around a number change its meaning: a
#: condition, a bound, a negation, another quantity, a sign, a rate ("per 100 m").
#: "as per Code", "By Contractor" and "Note - 2" are not among them.
_QUALIFIER = re.compile(
    r"\b(?:at|min(?:imum)?|max(?:imum)?|except(?:ing)?|excluding|not|only|when|if|unless|"
    r"during|normal|design|operating|rated|up\s+to|from|to|and|or)\b"
    r"|@|per\s+\d|^\s*[-+±]|\d\s*(?:°|deg\b|%|[a-z]{1,6}\b)",
    re.IGNORECASE,
)


def _around_the_number(fact: dict) -> str:
    """The stated text without the printed number and its unit."""
    text = " ".join(str(fact.get("field_value") or "").split())
    raw_value = str(fact.get("raw_value") or "").strip()
    unit = str(fact.get("raw_unit") or "").strip()
    at = text.lower().find(raw_value.lower()) if raw_value else -1
    if at < 0:
        return text  # not found as written: keep the whole text, the cautious way
    rest = text[at + len(raw_value) :].lstrip()
    if unit and rest.lower().startswith(unit.lower()):
        rest = rest[len(unit) :]
    return f"{text[:at]} {rest}".strip()


def key(fact: dict) -> tuple:
    """Two facts with the same key are one value."""
    base = same_value_key(fact)
    if base[0] == "t":
        return base  # text values are already compared as text
    around = _around_the_number(fact)
    if _QUALIFIER.search(around):
        return (*base, " ".join(around.lower().split()))
    return base
