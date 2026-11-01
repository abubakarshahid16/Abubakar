"""The words of the CRS rows that are drafts for an engineer (pure constants).

Moved out of `crs_mapping` (#1477) so that module does not grow: the sentences a
waiting AI / web draft prints in COMPANY Comments (owner order 2d/2f, spec e),
and the clause review's lane (`clause_review.py`): never a verdict, it rides in
"AI Review Comments" until an engineer confirms it, and is off the sheet if an
engineer rejects it. No imports, no db: `crs_mapping` stays pure.
"""

import re
from collections import defaultdict

#: Spec e: COMPANY Comments of an UNCONFIRMED AI / web item. Plain words that
#: the row is a suggestion awaiting an engineer - never the draft itself,
#: which stays in "AI Review Comments" (owner order 2d/2f).
AI_UNCONFIRMED_COMMENT = (
    "AI suggestion awaiting an engineer's decision - its words are in "
    "AI Review Comments. Not issued to the contractor until an engineer "
    "confirms it."
)
WEB_UNCONFIRMED_COMMENT = (
    "Web standards check suggestion awaiting an engineer's decision - its "
    "words are in AI Review Comments. Not issued to the contractor until "
    "an engineer confirms it."
)

#: The two waiting sentences. They are text ONLY beside the draft they point
#: to (a row's "AI Review Comments"); anywhere else - a carried-forward
#: snapshot, a row whose draft is gone - they say nothing true.
SPEC_UNCONFIRMED_COMMENT = (
    "Specification check suggestion (a DRAFT must-contain list, no AI) awaiting an "
    "engineer's decision - its words are in AI Review Comments. Not issued to the "
    "contractor until an engineer confirms it."
)
#: The waiting sentence of each draft origin; any origin not named uses the AI's.
UNCONFIRMED_COMMENTS = defaultdict(
    lambda: AI_UNCONFIRMED_COMMENT,
    {
        "web_standard_check": WEB_UNCONFIRMED_COMMENT,
        "spec_kit": SPEC_UNCONFIRMED_COMMENT,
    },
)
#: #1477: `review_findings.origin`, row kind and bylines of a clause review item.
CLAUSE_ORIGIN = "clause_review"
ROW_KIND_CLAUSE_REVIEW = "clause_review"
CLAUSE_CONFIRMED_BY = "AI clause review, confirmed by "
CLAUSE_UNCONFIRMED_BY = "AI clause review - engineer to confirm"
CLAUSE_LANE = (CLAUSE_CONFIRMED_BY, CLAUSE_UNCONFIRMED_BY, ROW_KIND_CLAUSE_REVIEW)

#: #1479: `review_findings.origin`, row kind and bylines of a specification kit item.
SPEC_ORIGIN = "spec_kit"
ROW_KIND_SPEC_KIT = "spec_kit"
SPEC_CONFIRMED_BY = "Specification check, confirmed by "
SPEC_UNCONFIRMED_BY = "Specification check (DRAFT list) - engineer to confirm"
SPEC_LANE = (SPEC_CONFIRMED_BY, SPEC_UNCONFIRMED_BY, ROW_KIND_SPEC_KIT)

#: #1484: the nouns of the parked kinds that reuse the specification lane (`spec_kit` kind kits).
KIND_NOUNS = ("drawing",)


def spec_lane_words(noun: str = "specification") -> tuple[str, str, str]:
    """(confirmed byline prefix, unconfirmed byline, waiting comment) of the kit lane for a kind's
    noun; "specification" gives the SPEC_* wording byte for byte."""
    name = noun.capitalize()
    return (
        SPEC_CONFIRMED_BY.replace("Specification", name, 1),
        SPEC_UNCONFIRMED_BY.replace("Specification", name, 1),
        SPEC_UNCONFIRMED_COMMENT.replace("Specification", name, 1),
    )


WAITING_COMMENTS = frozenset(
    {AI_UNCONFIRMED_COMMENT, WEB_UNCONFIRMED_COMMENT, SPEC_UNCONFIRMED_COMMENT}
    | {spec_lane_words(n)[2] for n in KIND_NOUNS}
)


_NOUN = re.compile(r"^A ([a-z]+) states: ")


def lane(f: dict, lanes: dict) -> tuple[str, str, str, str]:
    """(confirmed byline prefix, unconfirmed byline, row kind, waiting comment) of a draft
    finding's origin; a kit row (#1484) uses its document kind's noun, read from its requirement
    words, and a specification's wording is unchanged."""
    origin = f.get("origin")
    confirmed, unconfirmed, kind = lanes[origin]
    comment = UNCONFIRMED_COMMENTS[origin]
    if origin == SPEC_ORIGIN:
        found = _NOUN.match(f.get("requirement") or "")
        confirmed, unconfirmed, comment = spec_lane_words(
            found.group(1) if found else "specification"
        )
    return confirmed, unconfirmed, kind, comment
