"""Compliance language a sentence asserts, and whether its evidence asserts it.

WHAT THIS CATCHES, and it is narrow on purpose.

`synthesis._cite` already drops a sentence that cites nothing, and one that
carries a number no cited span contains. Both are strong rules because a
number is either in the page or it is not.

Words are different: prose is *supposed* to be reworded. "shall achieve" and
"specifies" are the same claim, and a check that required every content word
to appear in the source would delete every legitimate summary sentence this
product exists to produce.

So this module checks ONE class of wording, chosen because it is the class
where invention is most expensive in a specification tool: **an assertion of
compliance, approval or obligation**. Measured on a real answer:

    source   "...contains only data that has been through the quality
              control process."
    summary  "...quality-controlled data COMPLIANT WITH RELEVANT STANDARDS."

The citation resolved to a real page, so the existing checks passed it. The
sentence tells an engineer the data is standards-compliant, and the document
does not say that. In a coatings or civil specification, "compliant with
relevant standards" is the sentence somebody acts on.

WHAT THIS DOES NOT CATCH, stated plainly so nobody mistakes it for more than
it is:

  * A MERGE THAT MOVES A SUBJECT. The same answer produced "the Dataset was
    created with it in mind TO BEGIN WITH pre-defined data" from two source
    sentences where it is the WORKFLOW that begins with that data. Every word
    is in the source; the attachment is not. Detecting that needs parsing,
    not vocabulary, and pretending otherwise would be the invented-measurement
    defect one level up.
  * Ordinary paraphrase, in either direction. That is deliberate.
  * A claim asserted by implication rather than by these words.

It is a floor, not a proof. The docstring says so because a check whose limits
are undocumented gets trusted for things it never did.
"""

from __future__ import annotations

import re

#: Families of assertion. A sentence that asserts a family must cite a span
#: that asserts the SAME family - not merely a span on the same page.
#:
#: Grouped rather than listed flat so that "in accordance with" in the source
#: supports "conforms to" in the summary. Those are the same claim in
#: engineering prose, and splitting them would fire on honest rewording.
_FAMILIES: dict[str, tuple[str, ...]] = {
    "conformance": (
        r"complian\w*", r"conform\w*", r"in accordance with", r"accordance",
        r"meets the requirements", r"per\s+(?:iso|astm|api|norsok|nist|en)\b",
    ),
    "approval": (
        r"approv\w*", r"authoris\w*", r"authoriz\w*", r"accredit\w*",
        r"certifi\w*", r"endors\w*",
    ),
    "obligation": (
        r"\bshall\b", r"\bmust\b", r"\bmandator\w*", r"\brequired\b",
        r"\bis\s+required\b", r"\brequirement\b",
    ),
    "prohibition": (
        r"\bshall not\b", r"\bmust not\b", r"\bprohibit\w*", r"\bforbidden\b",
        r"\bnot permitted\b",
    ),
}

_COMPILED = {
    family: tuple(re.compile(p, re.IGNORECASE) for p in patterns)
    for family, patterns in _FAMILIES.items()
}

#: Prohibition is checked BEFORE obligation. "shall not" contains "shall", and
#: reporting a prohibition as an obligation would invert the claim - the worst
#: possible way to be wrong about a specification.
_ORDER = ("prohibition", "conformance", "approval", "obligation")


def families(text: str) -> frozenset[str]:
    """Assertion families this text makes.

    A prohibition suppresses the obligation it contains: "shall not be coated"
    asserts prohibition, not obligation.
    """
    found: set[str] = set()
    for family in _ORDER:
        if any(rx.search(text) for rx in _COMPILED[family]):
            found.add(family)
    if "prohibition" in found:
        found.discard("obligation")
    return frozenset(found)


def unsupported(sentence: str, spans: str) -> frozenset[str]:
    """Families the sentence asserts that its cited evidence does not.

    Empty means the sentence asserts nothing this module checks, or asserts
    only what the evidence also asserts. It never means the sentence is true.
    """
    return families(sentence) - families(spans)


#: What to tell a reader. Named per family because "unsupported assertion" is
#: not a sentence anyone can act on.
REASONS: dict[str, str] = {
    "conformance": "claims compliance with a standard that no cited span claims",
    "approval": "claims an approval that no cited span records",
    "obligation": "states a requirement that no cited span states",
    "prohibition": "states a prohibition that no cited span states",
}


def reason(family: str) -> str:
    return REASONS.get(family, f"asserts {family}, which no cited span asserts")
