"""COMPANY's usual position on cost and schedule, offered in a system draft for the engineer to confirm (lead-4's decision, 27 Nov 2026).

Builder H's blind look at seven approved replies: six state plainly that there are no grounds for a schedule or cost impact, while the
drafts deferred or stayed silent. That position is COMPANY's decision, so the MODEL never writes it: code adds one set sentence (an
INVENTED generic wording, never text taken from any approved reply; the owner may give his own wording later) as the draft's last
paragraph, and the page marks it so the engineer keeps it only if it applies. Nothing is added when the request itself raises cost or
schedule (then the position is the engineer's to state, and the page says so) or when the draft already speaks of a cost or schedule
impact. Local text handling only; nothing leaves the machine.
"""

from __future__ import annotations

import re

#: The set sentence: an INVENTED wording, written to stand apart from any approved reply (builder H's gate of #1963: the first draft of it
#: followed an approved reply's sentence too closely). Replace with the owner's own wording when he gives it.
POSITION_LINE = "On the information given, COMPANY finds no basis for a change to cost or schedule from this item."
#: The page's mark when the line was added.
POSITION_MARK = (
    "The last paragraph is COMPANY's usual position on cost and schedule, added from a set wording, not from the sources: "
    "keep it only if it applies to this query."
)
#: The page's mark when the request itself raises cost or schedule (no set wording is added).
RAISED_MARK = "The request raises cost or schedule: COMPANY's position on it is for the engineer to state; no set wording was added."

# the request ASKS about money or time (a claim, a change, more time, who pays, a delay): never answered by a set sentence. Widened
# after builder H's gate of #1963, which found "who bears the cost of ...", "... delay our work by 3 weeks" and "schedule relief" missed.
_RAISES = re.compile(
    r"\b(?:cost|schedule|time|price|commercial)\s+(?:impact|implication|claim)s?\b"
    r"|\bextension\s+of\s+time\b|\b(?:variation|change)\s+orders?\b|\bcompensat\w*"
    r"|\b(?:additional|extra)\s+(?:cost|costs|payment|time)\b|\breimburs\w*"
    r"|\bwho\s+(?:bears|pays|covers|funds|will\s+(?:bear|pay|cover|fund))\b|\bcosts?\s+of\b|\bat\s+whose\s+(?:cost|expense)\b"
    r"|(?<!time )\bdelay(?:s|ed|ing)?\b|\blate\b|\bslip(?:s|ped|page)?\b|\bbehind\s+schedule\b"
    r"|\bschedule\s+(?:relief|extension|slip|slippage|change)\b"
    r"|\bby\s+\d+\s+(?:weeks?|days?|months?)\b|\b\d+\s+(?:weeks?|days?|months?)\s+(?:late|behind|of\s+delay)\b",
    re.IGNORECASE,
)
# the draft already SPEAKS of a cost or schedule impact (a position, or a deferral the engineer must read): nothing is added
_SPEAKS = re.compile(
    r"\b(?:cost|schedule|time)\b[^.\n]{0,60}\bimpact|\bimpact\b[^.\n]{0,60}\b(?:cost|schedule)\b"
    r"|\b(?:cost|schedule)\s+(?:or|and)\s+(?:cost|schedule)\b",
    re.IGNORECASE,
)


def raises_cost(question: str) -> bool:
    """True when the request itself asks about cost or schedule (a claim, a change order, more time, compensation)."""
    return bool(_RAISES.search(question or ""))


def with_position(answer: str, question: str) -> str:
    """The system draft with the set sentence as its last paragraph, or unchanged (the request raises cost or schedule, the draft
    already speaks of an impact, or the sentence is already there)."""
    text = (answer or "").rstrip()
    if (
        not text
        or raises_cost(question)
        or _SPEAKS.search(text)
        or POSITION_LINE in text
    ):
        return answer
    return f"{text}\n\n{POSITION_LINE}"


def position_mark(answer: str | None, question: str, model_written: bool) -> str | None:
    """The page's mark for a model-written draft: the set sentence was added, or the request raises cost or schedule."""
    if not model_written or not answer:
        return None
    if POSITION_LINE in answer:
        return POSITION_MARK
    if raises_cost(question):
        return RAISED_MARK
    return None
