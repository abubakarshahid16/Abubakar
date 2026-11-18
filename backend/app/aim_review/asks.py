"""A sent comment must ASK something (order 14, lead 3, after the v3 strict judges: "pass statements sent as comments" were the judges'
WRONG). Pure code, no model, no call, nothing sent to Claude changes: this runs LAST, after every AI step, and only marks.

A line the judge marked "confirm" (nothing suspected, the value stated: the judge only asked the vendor to confirm it) whose comment
holds NO request at all (no question mark, no request word) says "the value is fine" or restates the paper: it is kept on "All points"
with the note `no_ask` and is not sent. A "concern" is touched ONLY when it states a pass (`states_a_pass`: a pass word, no contrast
or negation, no explicit request): the judge suspects the value, and a concern that only STATES a conflict ("the set pressure is
above the rating") carries no request word yet is a real find. A value left open (`ask` "open") IS the
question (the blank is what is asked), so it is never touched here either.

The request words are language, not values: a base-form request verb ("confirm", "state", "revise" ...) or a modal ("must", "should")
anywhere in the comment counts as a request, and so is a named GAP ("does not say how", "not given", "blank"). The lists are LIBERAL on purpose: a comment is dropped
only when nothing in it can be read as a request. Words that are mostly nouns ("size", "rate", "set", "name") are left out so a statement about a size is not a request.
"""

from __future__ import annotations

import re

#: The note a line carries when it asks nothing (`aim_review.NO_ASK`); the reason follows the colon.
NO_ASK_REASON = "states a pass or repeats the paper and asks nothing"

_REQUEST_WORDS = (
    "confirm|state|provide|clarify|specify|verify|justify|revise|add|advise|explain|demonstrate|submit|identify|resolve|correct|"
    "update|amend|include|supply|describe|define|indicate|reconsider|review|ensure|complete|fill|check|show|give|reply|respond|"
    "address|align|reduce|increase|replace|select|apply|enter|attach|cite|raise|lower|move|remove|keep|retain|consider|evaluate|"
    "calculate|recalculate|prove|reconcile|re-check|recheck|please|ask|need|needs|must|should|shall|required|requires|require|"
    "request|re-state|restate"
)
#: A GAP the comment names ("does not say how", "is not given", "blank", "cannot be checked", "missing") is a request too: the vendor is
#: being told what the paper lacks. Liberal on purpose, like the verbs.
_GAP = (
    r"(?:does|do|did)\s+not\s+\w+|\bnot\s+(?:stated|given|shown|specified|defined|provided|included|covered|addressed|identified|"
    r"mentioned|clear|available|known|set|filled|evidenced|demonstrated|supported)\b|\bnot\s+\w+ed\s+(?:on|in|by|for)\b|"
    r"\bno\s+\w+(?:\s+\w+)?\s+(?:is|are)\s+(?:given|stated|shown|specified|provided|defined)\b|\b(?:cannot|can\s?not|unable|"
    r"missing|blank|absent|unclear|unstated|undefined|omitted|lacks?|without|left\s+open|open\s+point)\b"
)
_REQUEST = re.compile(r"\b(" + _REQUEST_WORDS + r")\b|" + _GAP, re.IGNORECASE)


#: A PASS VERDICT (lead 3, after the fixed round of 18 Nov: the judge marked statements such as "the flange rating meets the
#: minimum" as concerns, and the strict judges called each WRONG). A Question, a concern included, whose comment is ONE sentence
#: stating a pass, with NO contrast, negation or comparison word and NO explicit request (a question mark, "please", a modal, or
#: a request verb opening a sentence), asks nothing. Narrow on purpose (review of d4dceeeb): "well above" is no pass (it is how a
#: conflict is stated too), and a figure beside any comparison word always stays sent.
_PASS = re.compile(
    r"\b(meets?|satisf(?:y|ies|ied)|compl(?:y|ies|iant)|acceptable|adequate|sufficient|conforms?|in line with|consistent with|"
    r"within (?:the )?(?:limit|range|rating|allowable)|is (?:fine|correct|ok))\b",
    re.IGNORECASE,
)
_CONTRA = re.compile(
    r"\b(not|no|never|exceed\w*|above|below|higher|lower|greater|less|more|over|under|than|while|yet|two|zero|different|"
    r"conflict\w*|differ\w*|inconsistent|but|however|although|whereas|instead|only|unless|mismatch\w*|contradict\w*|wrong|"
    r"incorrect|misleading|missing|blank|open)\b",
    re.IGNORECASE,
)
#: A figure beside a comparison word is a comparison, never a plain pass (it stays sent).
_COMPARE = re.compile(
    r"\b(above|below|higher|lower|greater|less|more|over|under|than|exceed\w*|within|up to|at (?:least|most))\b",
    re.I,
)
_EXPLICIT = re.compile(
    r"\?|\b(please|must|should|shall)\b|(?:^|[.;:]\s*)(confirm|state|provide|clarify|specify|verify|revise|add|advise|explain|"
    r"submit|correct|update|amend|include|supply|indicate|review|ensure|show|give|align|check)\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"[.;!?](?:\s|$)")


def states_a_pass(comment: str) -> bool:
    """The comment is ONE sentence stating a pass (`_PASS`) with no contrast, negation or comparison word, no figure beside a
    comparison word, and no explicit request: it asks nothing."""
    text = str(comment or "").strip()
    if len([x for x in _SENTENCE_END.split(text) if x.strip()]) != 1:
        return False
    if any(c.isdigit() for c in text) and _COMPARE.search(text):
        return False
    return (
        bool(_PASS.search(text))
        and not _CONTRA.search(text)
        and not _EXPLICIT.search(text)
    )


def has_request(comment: str) -> bool:
    """Does the comment ask the vendor for anything? A question mark, or any request word (liberal: see the module note)."""
    text = str(comment or "")
    return "?" in text or bool(_REQUEST.search(text))


def asks_nothing(line: dict) -> bool:
    """A Question the judge only asked the vendor to CONFIRM (its mark is "confirm", never "concern"), its value not left open, with a
    comment that requests nothing. Any other line (another label, a concern, an open value, an unrecorded mark of an older run) is
    never judged here."""
    if (
        line.get("label") != "Question"
        or line.get("ask")
        not in (
            "confirm",
            "concern",
        )  # a value left open is the question; an older run (no mark) is never touched
        or line.get("deferred")
    ):
        return False
    comment = line.get("comment") or ""
    if line.get("ask") == "confirm" and not has_request(comment):
        return True
    return states_a_pass(comment)  # a concern too, when it only states a pass (`_PASS`)


def mark(decided: list[dict]) -> int:
    """Append the `no_ask` note to every decided line that asks nothing and would be sent (in place; the line stays on "All points").
    Returns how many. Runs after the last AI step, so no step sees a different list."""
    from . import NO_ASK, sendable
    from .engine import to_line

    marked = 0
    for n, d in enumerate(decided, 1):
        if sendable(to_line(n, d)) and asks_nothing(d):
            d["code"] = "; ".join(
                x for x in (d.get("code"), f"{NO_ASK}: {NO_ASK_REASON}") if x
            )
            marked += 1
    return marked
