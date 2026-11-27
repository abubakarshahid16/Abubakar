"""COMPANY's usual position on cost and schedule, offered in a system draft for the engineer to confirm (lead-4's decision, 27 Nov 2026).

Builder H's blind look at seven approved replies: six state plainly that there are no grounds for a schedule or cost impact, while the
drafts deferred or stayed silent. That position is COMPANY's decision, so the MODEL never writes it: code adds one set sentence (an
INVENTED generic wording, never text taken from any approved reply; the owner may give his own wording later) as the draft's last
paragraph, and the page marks it so the engineer keeps it only if it applies. Nothing is added when the request mentions money or time
at all (then the position is the engineer's to state, and the page says so) or when the draft already speaks of a cost or schedule
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
#: The page's mark when the request mentions money or time (no set wording is added). "Mentions", not "raises": the check is by words.
RAISED_MARK = (
    "The request mentions money or time, so no set wording on cost and schedule was added: "
    "COMPANY's position on it, if any, is for the engineer to state."
)

# THE RULE IS FLIPPED (builder H's second gate of #1963, confirmed by lead-4, 27 Nov 2026): a missed set sentence is safe, a wrongly added
# one is the danger. So the sentence is added ONLY when the request holds NO money or time word at all. Technical uses that only look
# like money or time are left out: an instrument's "time delay", a pipe "schedule 80" or a contract's "Schedule B", a "slip-on" flange,
# a "push button", a flow or corrosion "rate", seismic "acceleration", a part "behind" another.
_MONEY = (
    r"\bcosts?\b|\bcosted\b|\bcostly\b|\bprices?\b|\bpricing\b|\bpa(?:y|ys|id|ying|yment|yments)\b|\bexpenses?\b|\bbudget\w*"
    r"|\bcommercial\w*|\bclaims?\b|\bclaimed\b|\bcompensat\w*|\breimburs\w*|\bman-?hours?\b|\bmanhours?\b"
    r"|\b(?:unit|hourly|daily|labou?r|day)\s+rates?\b|\b(?:variation|change)\s+orders?\b|\binvoice\w*|\bcontract\s+(?:price|sum|value)\b"
)
_TIME = (
    r"\b(?:extra|additional|more)\s+time\b|\bextensions?\b|(?<!time )\bdelay(?:s|ed|ing)?\b|\blate\b|\bslip(?:s|ped|page)?\b(?![- ](?:on|joint|blind|ring|plate|type))"
    r"|\bmilestones?\b|\b(?:completion|delivery|handover|start[- ]?up|target|due)\s+dates?\b|\bbehind\s+(?:schedule|plan|programme|program)\b"
    r"|\bpush(?:es|ed|ing)?\s+(?:back|out)\b|\bpush(?:es|ed|ing)?\s+(?:the|our|its)\s+[\w\s-]{0,30}?\bdates?\b"
    r"|\bpostpon\w*|\baccelerat\w*\s+(?:the\s+)?(?:work|works|schedule|programme|program|delivery|completion)\b"
    r"|\b\d+\s*(?:-\s*)?(?:days?|weeks?|months?)\b|\bschedule\b(?!\s*(?:[A-H]\b|[A-H]-?\d|\d|XS\b|XXS\b|STD\b))(?<!pipe schedule)"
)
_RAISES = re.compile(f"{_MONEY}|{_TIME}", re.IGNORECASE)
# the draft already SPEAKS of a cost or schedule impact (a position, or a deferral the engineer must read): nothing is added
_SPEAKS = re.compile(
    r"\b(?:cost|schedule|time)\b[^.\n]{0,60}\bimpact|\bimpact\b[^.\n]{0,60}\b(?:cost|schedule)\b"
    r"|\b(?:cost|schedule)\s+(?:or|and)\s+(?:cost|schedule)\b",
    re.IGNORECASE,
)


def raises_cost(question: str) -> bool:
    """True when the request holds ANY money or time word (the flipped rule): then no set sentence is added."""
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
