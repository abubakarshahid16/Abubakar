"""ONE vocabulary of limit-direction words (#915, PF2).

THE DEFECT THIS REMOVES. `reader_api` kept its own `_CEILING` / `_FLOOR` lists
beside `claims._COMPARATOR_WORDS` and `requirements_3b._OPERATOR`. The reader's
lists lacked "less than", "greater than", "more than", "below", "above",
"under", "over", "up to", "or less", "or more", "<", ">" and the symbols
<= and >=. When none matched, the quote had "no direction" and rule 4 - the
rule that holds a model's parsed limit against what the sentence says - never
fired, so a model answer with the WRONG operator was accepted after two runs
agreed with each other.

HOW IT IS ONE VOCABULARY. The vocabulary of `claims` stays the authority for
the words it has (it feeds the claims engine and `requirements_3b`); this
module adds the words it lacks, in the same notation, and answers ONE question
on top of both: which way does a sentence say a limit points. A drift test
(`test_915_one_direction_vocabulary.py`) fails when a phrase `claims` or
`requirements_3b` knows is read here in the other direction.

WHAT IT NEVER DOES: guess. A sentence with both families ("the minimum cover
shall not exceed 50 mm") has no direction here, and a sentence with none has
none; the caller holds it for the engineer. A weak word that is ordinary prose
as often as a comparator ("over", "under", "above", "below", "up to") counts
only when a number follows it.
"""
from __future__ import annotations

import re

from . import claims

CEILING = "<="
FLOOR = ">="

_COMPARATIVES = r"(?:higher|larger|bigger|greater|more|thicker|longer|wider|taller|heavier|faster)"
_COMPARATIVES_LOW = r"(?:lower|smaller|less|fewer|thinner|shorter|narrower|lighter|slower|closer)"
_NEG = r"(?:shall\s+|must\s+|may\s+|should\s+|will\s+|is\s+to\s+|are\s+to\s+)?(?:not|never)\s+(?:\w+\s+){0,2}?"
#: a weak word counts only in front of a number: "over 5 mm" yes, "over time" no
_BEFORE_A_NUMBER = r"(?=\s*(?:of\s+)?[-+−]?\d)"

#: (pattern, direction): the order is the policy - negated forms first, so a
#: negation is absorbed by the phrase it belongs to and the bare word that
#: follows it is never read on its own.
_EXTRA_WORDS: tuple[tuple[str, str | None], ...] = (
    # negated: "not higher than", "no more than", "shall not be set higher than"
    (r"in\s+no\s+case\s+(?:shall|may|should|will)\s+(?:it\s+)?(?:be\s+)?" + _COMPARATIVES_LOW + r"\s+than", FLOOR),
    (r"in\s+no\s+case\s+(?:shall|may|should|will)\s+(?:it\s+)?(?:be\s+)?" + _COMPARATIVES + r"\s+than", CEILING),
    (_NEG + _COMPARATIVES_LOW + r"\s+than", FLOOR),
    (_NEG + _COMPARATIVES + r"\s+than", CEILING),
    (r"(?:no|not)\s+(?:be\s+)?(?:" + _COMPARATIVES + r")\s+than", CEILING),
    (_NEG + r"(?:below|under|beneath)\b" + _BEFORE_A_NUMBER, FLOOR),
    (_NEG + r"(?:above|over)\b" + _BEFORE_A_NUMBER, CEILING),
    (r"not\s+to\s+exceed", CEILING),
    (r"not\s+be\s+exceeded", CEILING),
    (r"no\s+(?:more|greater|higher)\s+than", CEILING),
    (r"no\s+(?:less|lower|smaller|fewer)\s+than", FLOOR),
    # bare
    (r"\bor\s+(?:less|fewer|lower|smaller|below|under)\b", CEILING),
    (r"\bor\s+(?:more|greater|higher|larger|above|over)\b", FLOOR),
    (r"\bup\s+to\b" + _BEFORE_A_NUMBER, CEILING),
    (r"(?:below|under|beneath)\b" + _BEFORE_A_NUMBER, CEILING),
    (r"(?:above|over)\b" + _BEFORE_A_NUMBER, FLOOR),
    (_COMPARATIVES_LOW + r"\s+than", CEILING),
    (_COMPARATIVES + r"\s+than", FLOOR),
    (r"\bmax\b\.?", CEILING),
    (r"\bmin\b\.?", FLOOR),
)

_CLAIMS_DIRECTION = {">=": FLOOR, ">": FLOOR, "min": FLOOR, "<=": CEILING, "<": CEILING, "max": CEILING}

def _anchored(pattern: str) -> str:
    """A phrase that starts with a letter starts at a word. `claims` writes
    "min", dot optional, for a place where a number follows it; here the same
    pattern would also match inside "nominal"."""
    return rf"\b(?:{pattern})" if re.match(r"[A-Za-z(]", pattern) else pattern


_FROM_CLAIMS = [(_anchored(p), _CLAIMS_DIRECTION[sym]) for p, sym in claims._COMPARATOR_WORDS
                if sym in _CLAIMS_DIRECTION and sym not in ("min", "max")]
_LONG = [(p, d) for p, d in _FROM_CLAIMS if p.startswith("\\b")]
_SYMBOLS = [(p, d) for p, d in _FROM_CLAIMS if not p.startswith("\\b")]
_WORDS_MIN_MAX = [(r"\bminimum(?:\s+of)?\b", FLOOR), (r"\bmaximum(?:\s+of)?\b", CEILING)]

#: (compiled pattern, direction) in priority order: the words of `claims` and
#: this module, negated forms before the bare ones they contain, symbols last.
#: Equality ("=") is no direction and is left out.
_ALL: tuple[tuple[re.Pattern, str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), d)
    for p, d in (*_LONG, *_EXTRA_WORDS, *_WORDS_MIN_MAX, *_SYMBOLS) if d is not None)

_ALTERNATION = re.compile("|".join(f"(?P<g{i}>{p.pattern})" for i, (p, _d) in enumerate(_ALL)), re.IGNORECASE)
_FOLD = re.compile(r"\s+")
_NEGATION = re.compile(r"\b(?:not|never|no|nor)\b|n't\b", re.IGNORECASE)


def directions_in(text: str | None) -> list[str]:
    """The direction of each comparator phrase in `text`, left to right. Each
    phrase is read once: a negated form consumes the words it contains."""
    folded = _FOLD.sub(" ", (text or "").replace("−", "-")).strip()
    found: list[str] = []
    for match in _ALTERNATION.finditer(folded):
        index = int(match.lastgroup[1:])
        direction = _ALL[index][1]
        # A NEGATION A FEW WORDS BEFORE A PHRASE THAT DID NOT ABSORB IT is
        # not read: "shall not be the thing higher than 5" may mean either,
        # and a guess is the one thing this vocabulary never makes. Both
        # directions are recorded, so the sentence is held.
        if not _NEGATION.search(match.group(0)) and _NEGATION.search(" ".join(folded[:match.start()].split()[-5:])):
            found.extend((CEILING, FLOOR))
        else:
            found.append(direction)
    return found


def direction_of(text: str | None) -> str | None:
    """`"<="` (a ceiling), `">="` (a floor), or None. ONLY THE DIRECTION, never
    the strictness: "less than" and "not exceed" are both ceilings.

    None when the words state no direction, and None when they state BOTH -
    a sentence the caller must not guess about."""
    found = set(directions_in(text))
    if len(found) == 1:
        return found.pop()
    return None
