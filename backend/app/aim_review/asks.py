"""A sent comment must ASK something (order 14, lead 3, after the v3 strict judges: "pass statements sent as comments" were the judges'
WRONG). Pure code, no model, no call, nothing sent to Claude changes: this runs LAST, after every AI step, and only marks.

A line the judge marked "confirm" (nothing suspected, the value stated: the judge only asked the vendor to confirm it) whose comment
holds NO request at all (no question mark, no request word) says "the value is fine" or restates the paper: it is kept on "All points"
with the note `no_ask` and is not sent. A "concern" is NEVER touched: the judge suspects the value, and a concern that only STATES a
conflict ("the set pressure is above the rating") carries no request word yet is a real find. A value left open (`ask` "open") IS the
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


def has_request(comment: str) -> bool:
    """Does the comment ask the vendor for anything? A question mark, or any request word (liberal: see the module note)."""
    text = str(comment or "")
    return "?" in text or bool(_REQUEST.search(text))


def asks_nothing(line: dict) -> bool:
    """A Question the judge only asked the vendor to CONFIRM (its mark is "confirm", never "concern"), its value not left open, with a
    comment that requests nothing. Any other line (another label, a concern, an open value, an unrecorded mark of an older run) is
    never judged here."""
    return (
        line.get("label") == "Question"
        and line.get("ask") == "confirm"
        and not line.get("deferred")
        and not has_request(line.get("comment") or "")
    )


def mark(decided: list[dict]) -> int:
    """Append the `no_ask` note to every decided line that asks nothing and would be sent (in place; the line stays on "All points").
    Returns how many. Runs after the last AI step, so no step sees a different list."""
    from . import NO_ASK, sendable
    from .engine import to_line

    marked = 0
    for n, d in enumerate(decided, 1):
        if not sendable(to_line(n, d)):
            continue
        why = (
            NO_WORDS_REASON
            if has_no_words(d)
            else (NO_ASK_REASON if asks_nothing(d) else "")
        )
        if why:
            d["code"] = "; ".join(x for x in (d.get("code"), f"{NO_ASK}: {why}") if x)
            marked += 1
    return marked


#: Why a line whose own comment has no words is not sent (update 5's quick score: the judge gave a pass as an empty comment and
#: numbers, code marked it "concern", and the empty line was sent alone or as a group of empty members).
NO_WORDS_REASON = "the comment has no words"


def has_no_words(line: dict) -> bool:
    """The line's OWN comment holds no words (empty or only spaces), whatever its label or mark: there is nothing to send. Not a
    word list: an empty text is empty."""
    return not str(line.get("comment") or "").strip()
