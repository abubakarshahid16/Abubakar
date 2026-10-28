"""A "should" sentence of a standard is a RECOMMENDATION, recorded as its own type (order 288.2).

API RP 520 is a Recommended Practice: about 150 of its sizing and set-pressure sentences say
"should", and the extractor kept none of them. For a sheet whose design standard is RP 520 those
sentences are what the contract adopts. They are recorded now, as `requirement_type =
"recommendation"`, and a recommendation is never a limit:

* no number is kept from it (the sentence is advice, not a threshold), so a comparison cannot
  read it as a limit and it can never be matched to a sheet value;
* `standards.is_reviewable` refuses it to every existing review path, so nothing that reads
  requirements today can turn it into "does not meet";
* a sentence with "shall" / "must" AND "should" stays the mandatory requirement it was.

How a review raises a recommendation (a query to the engineer, never a verdict) is a separate step.
"""

from __future__ import annotations

import re

TYPE = "recommendation"

#: "should" and "should not" only. "may" is permission and "recommended" is not matched: the
#: coverage audit named "should" (4 of 147 held) and those are the words the owner asked for.
_RECOMMEND = re.compile(r"\bshould(?:\s+not)?\b", re.IGNORECASE)


def is_recommendation(sentence: str) -> bool:
    return bool(_RECOMMEND.search(sentence or ""))


def classify(sentence: str, limit: dict | None, mandatory: bool) -> str:
    """The stored type: a recommendation when no mandatory word is in the sentence, else what the
    parser always said."""
    from . import requirements_3b

    return requirements_3b.classify(sentence, limit) if mandatory else TYPE
