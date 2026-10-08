"""Linking a datasheet field to a clause: synonyms, nozzle marks, and simple
categorical values. CRS quick wins, 2026-09-27 (audit crs.md defect 3).

WHY. `comparison.match_by_containment` paired a field with a clause only when
the field's name appeared WORD FOR WORD in the clause's subject, and only when
the field held a number. Measured on the audit's planted-defect sheets that
hid a hydrotest shortfall ("hydrostatic test pressure" never meets "HYDROTEST
PRESSURE"), a nozzle-size breach ("nozzle size" never meets "N3 SIZE"), a
flange class breach (CL150 is not a number) and every "vendor to advise"
field (a blank is not a number).

THREE THINGS, ALL DETERMINISTIC, NO MODEL:

  * `canonical` rewrites a text's field words to one spelling per quantity,
    from `reference/field_synonyms.json`, on BOTH sides of the containment
    test. The data file is the rule; this module only applies it.
  * `field_of` reads a nozzle-mark field ("n3 size") as the nozzle's field
    ("nozzle size") and keeps the mark ("N3") as the ITEM the value is about,
    the same way an equipment tag is.
  * `categorical_requirement` / `compare_categorical` read the few closed,
    ordered answers a clause states outright - a flange class, a radiography
    extent, whether PWHT is performed - and compare a datasheet's answer with
    them. Anything else is not guessed: it returns None and the finding stays
    an engineer's question.

A CONDITIONAL CLAUSE IS NEVER DECIDED HERE. "Full radiography ... for vessels
in sour service" says nothing about a vessel nobody has shown to be in sour
service; `compare_categorical` reports the difference as a question
(NEEDS_ENGINEER_REVIEW), never as a breach.

Pure: no db, no app imports.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

SYNONYMS_PATH = Path(__file__).parent / "reference" / "field_synonyms.json"


def _fold(text: str | None) -> str:
    """The same fold `comparison._normalise_for_match` applies."""
    folded = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", folded).strip()


@lru_cache(maxsize=4)
def _table(path: str = str(SYNONYMS_PATH)) -> tuple[re.Pattern | None, dict[str, str], frozenset[str]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    to_canonical: dict[str, str] = {}
    for canonical_name, spellings in (data.get("groups") or {}).items():
        for spelling in [canonical_name, *spellings]:
            folded = _fold(spelling)
            if folded:
                to_canonical.setdefault(folded, _fold(canonical_name))
    # LONGEST SPELLING FIRST, so "npsh required" is read before "npsh".
    ordered = sorted(to_canonical, key=len, reverse=True)
    pattern = (re.compile(r"(?<!\w)(?:" + "|".join(re.escape(s) for s in ordered) + r")(?!\w)")
               if ordered else None)
    attributes = frozenset(_fold(a) for a in data.get("nozzle_attributes") or ())
    return pattern, to_canonical, attributes


def canonical(text: str | None) -> str:
    """`text` folded, with every synonym rewritten to its canonical phrase.

    One pass, left to right, longest spelling first: a canonical phrase that
    is itself inside a longer spelling is never rewritten twice.
    """
    folded = _fold(text)
    pattern, to_canonical, _attributes = _table()
    if not folded or pattern is None:
        return folded
    return pattern.sub(lambda m: to_canonical[m.group(0)], folded)


#: "n3 size", "n12a rating" - a nozzle mark then one nozzle attribute.
_NOZZLE_MARK = re.compile(r"^n(?P<mark>\d{1,2}[a-z]?)\s+(?P<attr>\w+)$")


def field_of(fact_name: str | None) -> tuple[str, str | None]:
    """`(canonical field name, item)` for one fact's field name.

    `item` is the nozzle mark ("N3") when the field is named after one, else
    None - the equipment tag, when there is one, is on the fact itself.
    """
    folded = _fold(fact_name)
    match = _NOZZLE_MARK.match(folded)
    _pattern, _to, attributes = _table()
    if match and match.group("attr") in attributes:
        return canonical(f"nozzle {match.group('attr')}"), f"N{match.group('mark').upper()}"
    return canonical(folded), None


# ------------------------------------------------ closed categorical values

#: The ASME B16.5 pressure classes, in order. A class is compared by its
#: number, and only these numbers are classes.
_CLASSES = (150, 300, 400, 600, 900, 1500, 2500)
_CLASS_IN_TEXT = re.compile(r"\b(?:class|cl\.?)\s*[-#]?\s*(150|300|400|600|900|1500|2500)\b"
                            r"|\b(150|300|400|600|900|1500|2500)\s*#", re.IGNORECASE)
#: Radiography extent, weakest to strongest.
_RT_LEVELS = {"none": 0, "nil": 0, "no": 0, "spot": 1, "partial": 1, "random": 1,
              "full": 2, "100%": 2, "100 %": 2}
_RT_IN_TEXT = re.compile(r"\b(full|spot|partial|random)\s+radiograph|\b(100\s?%)\s+radiograph"
                         r"|radiograph\w*\s+(?:shall\s+be\s+)?(full|spot|100\s?%)", re.IGNORECASE)
_AT_LEAST = re.compile(r"\b(?:minimum|at least|not less than|or higher|or above|or greater)\b",
                       re.IGNORECASE)
#: A CEILING: "shall not exceed Class 600", "maximum Class 600".
_AT_MOST = re.compile(r"\b(?:shall\s+not\s+exceed|must\s+not\s+exceed|not\s+(?:to\s+)?exceed"
                      r"|maximum|at\s+most|not\s+more\s+than|not\s+greater\s+than"
                      r"|or\s+lower|or\s+less|or\s+below)\b", re.IGNORECASE)
#: A PROHIBITION of the value named: "Class 150 flanges shall not be used".
_FORBIDDEN = re.compile(r"\b(?:shall|must|may)\s+not\s+be\s+(?:used|permitted|allowed|accepted|"
                        r"acceptable|installed|supplied|specified)\b|\bnot\s+(?:permitted|allowed)\b"
                        r"|\bprohibited\b", re.IGNORECASE)
#: "X is not required" / "need not" - NOT a requirement at all: it neither
#: demands X nor forbids it. Read as a requirement it was a false breach.
_NOT_REQUIRED = re.compile(r"\bnot\s+(?:be\s+)?(?:required|mandatory|necessary|needed)\b"
                           r"|\bneed\s+not\b|\bnot\s+applicable\b|\boptional\b", re.IGNORECASE)
#: Any other negation. A clause that negates something this reader has no
#: rule for is left to the engineer - never read as if the "not" were absent.
_NEGATION = re.compile(r"\b(?:not|no|never|nor|without)\b|n't\b", re.IGNORECASE)
_SHALL_DO = re.compile(r"\bshall\s+be\s+(?:performed|provided|carried\s+out|applied|required|done)\b",
                       re.IGNORECASE)
_SHALL_NOT_DO = re.compile(r"\b(?:shall|must)\s+not\s+be\s+(?:performed|carried\s+out|applied|done)\b",
                           re.IGNORECASE)
#: Words that make a clause CONDITIONAL. A conditional clause is compared,
#: but never decided: the difference is reported for an engineer to judge.
#: Audit 2026-09-30: a size scope ("nozzles 2 inch and larger") is a
#: condition too - a Class 150 answer for a 1 inch nozzle breaks nothing.
_CONDITION = re.compile(r"\b(?:when|where|if|unless|provided\s+that|except|in\s+\w+\s+service"
                        r"|for\s+\w+\s+service|and\s+(?:larger|smaller|above|below|over|under)"
                        r"|or\s+(?:larger|smaller))\b", re.IGNORECASE)

#: Which canonical field names answer each family.
FAMILY_FIELDS = {
    "flange_rating": frozenset({"flange rating"}),
    "radiography": frozenset({"radiography"}),
    "pwht": frozenset({"pwht"}),
}


_JOINED_CLASS = re.compile(r"(?:\band\b|\bor\b|,|/)\s*(150|300|400|600|900|1500|2500)\b"
                           r"(?!\s*(?:#|mm|in\b|inch|\"|°|deg|bar|psi|kpa|mpa))", re.IGNORECASE)


def _flange_rule(sentence: str) -> tuple[str, object, str] | None:
    """(operator, value, shown) for a flange-class clause, or None.

    Audit 2026-09-30 - the first class number used to be read as "must equal"
    whatever the sentence said around it: "shall not exceed Class 600", "Class
    150 flanges shall not be used" and "Class 150 or Class 300" all produced a
    false NON_COMPLIANT. Each shape is now read for what it says, and a shape
    not recognised here gives NO rule (the engineer reads it), never a verdict.
    """
    numbers = [int(m.group(1) or m.group(2)) for m in _CLASS_IN_TEXT.finditer(sentence)]
    # A BARE class number joined on ("Class 150 and 300", "Class 150/300") is
    # a second class too - read as one class, the clause lost half its words.
    numbers += [int(n) for n in _JOINED_CLASS.findall(sentence)]
    distinct = list(dict.fromkeys(numbers))
    if not distinct:
        return None
    if len(distinct) == 1:
        number = distinct[0]
        shown = f"Class {number}"
        if _AT_MOST.search(sentence):
            if _AT_LEAST.search(sentence):
                return None     # a floor and a ceiling on one number: unclear
            return "<=", number, shown
        if _FORBIDDEN.search(sentence):
            return "!=", number, shown
        if _NEGATION.search(sentence):
            return None
        return (">=" if _AT_LEAST.search(sentence) else "=="), number, shown
    # SEVERAL CLASSES. "Class 150 or Class 300" is a set of alternatives; any
    # other combination (a range, a table of sizes, "150 and 300") is not
    # read here.
    if _NEGATION.search(sentence) or _AT_LEAST.search(sentence) or _AT_MOST.search(sentence):
        return None
    between = _CLASS_IN_TEXT.sub("|", sentence).split("|")[1:-1]
    if between and all(re.fullmatch(r"\s*(?:,|or|,\s*or)\s*", gap, re.IGNORECASE)
                       for gap in between):
        return "in", tuple(distinct), " or ".join(f"Class {n}" for n in distinct)
    return None


def categorical_requirement(text: str | None) -> dict | None:
    """The closed value a clause states, or None.

    `{"family", "operator", "value", "shown", "condition"}` where `operator`
    is ">=" (a minimum: "minimum class 300"), "<=" (a ceiling: "shall not
    exceed Class 600"), "==" (exactly), "!=" (a prohibited value: "Class 150
    flanges shall not be used") or "in" (alternatives: "Class 150 or Class
    300", `value` a tuple), and `condition` is the clause's conditional
    phrase, or None.

    WHEN UNSURE, NONE. A clause saying something is NOT required, or negating
    something this reader has no rule for, yields no categorical rule: the
    pairing falls back to a question for the engineer, never a verdict.
    """
    sentence = " ".join((text or "").split())
    if not sentence:
        return None
    if _NOT_REQUIRED.search(sentence):
        return None
    condition = _CONDITION.search(sentence)
    cond = sentence[condition.start():].rstrip(".") if condition else None
    if condition and re.match(r"(?:and|or)\s", condition.group(0), re.IGNORECASE):
        # A size scope sits inside the subject ("Flanges on nozzles 2 inch
        # and larger shall ..."): the condition is that whole subject.
        cond = "for " + re.split(r"\s+(?:shall|must)\b", sentence, maxsplit=1,
                                 flags=re.IGNORECASE)[0].rstrip(",")
    folded = canonical(sentence)
    if "flange rating" in folded or re.search(r"\bflanges?\b", sentence, re.IGNORECASE):
        if _CLASS_IN_TEXT.search(sentence):
            rule = _flange_rule(sentence)
            if rule is None:
                return None
            operator, value, shown = rule
            return {"family": "flange_rating", "operator": operator,
                    "value": value, "shown": shown, "condition": cond}
    if "radiography" in folded or re.search(r"radiograph", sentence, re.IGNORECASE):
        found = list(_RT_IN_TEXT.finditer(sentence))
        if found:
            words = {next(g for g in m.groups() if g).lower().replace(" ", "") for m in found}
            levels = {_RT_LEVELS.get(w) for w in words}
            # One extent, stated positively. A negated extent ("full
            # radiography shall not be ...") or two extents is not read.
            if len(levels) == 1 and None not in levels and not _NEGATION.search(sentence):
                word = next(iter(words))
                # "Full radiography shall be performed" is a MINIMUM: more is
                # never a breach of it.
                return {"family": "radiography", "operator": ">=", "value": levels.pop(),
                        "shown": f"{word} radiography", "condition": cond}
            return None
    if "pwht" in folded:
        if _SHALL_NOT_DO.search(sentence):
            return {"family": "pwht", "operator": "==", "value": False,
                    "shown": "no PWHT", "condition": cond}
        if _SHALL_DO.search(sentence) and not _NEGATION.search(sentence):
            return {"family": "pwht", "operator": "==", "value": True,
                    "shown": "PWHT performed", "condition": cond}
    return None


_YES = frozenset({"yes", "y", "required", "reqd", "req d", "applicable", "performed"})
_NO = frozenset({"no", "n", "not required", "none", "nil", "n a", "na", "not applicable"})


def read_categorical(family: str, value: str | None) -> int | bool | None:
    """A datasheet answer read in `family`'s terms, or None when it does not
    read as one (a free-text answer is never guessed into a class)."""
    text = " ".join((value or "").split())
    if not text:
        return None
    if family == "flange_rating":
        found = re.fullmatch(r"(?:class|cl\.?)?\s*[-#]?\s*(\d{3,4})\s*#?(?:\s*(?:rf|ff|rtj))?",
                             text, re.IGNORECASE)
        number = int(found.group(1)) if found else None
        return number if number in _CLASSES else None
    if family == "radiography":
        return _RT_LEVELS.get(text.lower())
    if family == "pwht":
        folded = _fold(text)
        if folded in _YES:
            return True
        if folded in _NO:
            return False
    return None


def compare_categorical(rule: dict, provided: str | None) -> dict | None:
    """`{"status", "rationale"}` for one datasheet answer against `rule`, or
    None when the answer does not read in the rule's terms.

    Statuses are the comparison engine's words, as literals (this module
    stays pure): COMPLIANT, NON_COMPLIANT, NEEDS_ENGINEER_REVIEW.
    """
    got = read_categorical(rule["family"], provided)
    if got is None:
        return None
    operator = rule["operator"]
    if operator == ">=":
        ok = got >= rule["value"]
    elif operator == "<=":
        ok = got <= rule["value"]
    elif operator == "!=":
        ok = got != rule["value"]
    elif operator == "in":
        ok = got in rule["value"]
    elif operator == "==":
        ok = got == rule["value"]
    else:
        return None     # an operator this function does not know: no verdict
    shown = " ".join((provided or "").split())
    required = {">=": f"minimum {rule['shown']}", "<=": f"maximum {rule['shown']}",
                "!=": f"any rating other than {rule['shown']}"}.get(operator, rule["shown"])
    if rule.get("condition"):
        return {"status": "NEEDS_ENGINEER_REVIEW",
                "rationale": (
                    f"conditional_categorical: the clause requires {required} "
                    f"{rule['condition']}; the datasheet states {shown}, which "
                    f"{'meets' if ok else 'does not meet'} it IF the condition holds. "
                    "Whether it holds is not established by the datasheet, so no "
                    "verdict was made")}
    return {"status": "COMPLIANT" if ok else "NON_COMPLIANT",
            "rationale": (f"the datasheet states {shown}, which "
                          f"{'meets' if ok else 'does not meet'} the required "
                          f"{required}")}
