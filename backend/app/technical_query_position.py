"""COMPANY's usual position on cost and schedule: a set sentence OFFERED to the engineer beside the draft, never put in by code (lead-4's
final design, 27 Nov 2026, after three rounds of builder H's gate showed that no word list tells reliably whether a request raises money
or time).

Builder H's blind look at seven approved replies: most state plainly that there are no grounds for a schedule or cost impact. That is
COMPANY's decision, so neither the model nor this code ever writes it into a draft. The page shows the sentence (an INVENTED wording,
never text taken from any approved reply; the owner may give his own wording later) with one action that adds it to the engineer's own
reply. The word check below is only a quiet HINT above that action ("this request mentions money or time: state COMPANY's position
yourself"); it never adds, blocks or decides anything. Local text handling only; nothing leaves the machine.
"""

from __future__ import annotations

import re

#: The set sentence: an INVENTED wording, written to stand apart from any approved reply (builder H's gate of #1963: the first draft of it
#: followed an approved reply's sentence too closely). Replace with the owner's own wording when he gives it.
POSITION_LINE = "On the information given, COMPANY finds no basis for a change to cost or schedule from this item."
#: The quiet hint above the action when the request mentions money or time (a word check: a hint, never a gate).
HINT = "This request mentions money or time: state COMPANY's position yourself."

# The money and time words behind the HINT (built over builder H's gates of #1963). It is only a hint: a request it misses still gets the
# engineer's own judgement, since nothing is ever added without the engineer. Technical uses that only look like money or time are left out: an instrument's "time delay", a pipe "schedule 80" or a contract's "Schedule B", a "slip-on" flange,
# a "push button", a flow or corrosion "rate", seismic "acceleration", a part "behind" another.
_MONEY = (
    r"\bcosts?\b|\bcosted\b|\bcostly\b|\bprices?\b|\bpricing\b|\bpa(?:y|ys|id|ying|yment|yments)\b|\bexpenses?\b|\bbudget\w*"
    r"|\bcommercial\w*|\bclaims?\b|\bclaimed\b|\bcompensat\w*|\breimburs\w*|\bman[- ]?hours?\b|\bmanhours?\b"
    r"|\b(?:unit|hourly|daily|labou?r|day)\s+rates?\b|\b(?:variation|change)\s+orders?\b|\binvoice\w*|\bcontract\s+(?:price|sum|value)\b"
)
_TIME = (
    r"\b(?:extra|additional|more)\s+time\b|\bextensions?\b|(?<!time )\bdelay(?:s|ed|ing)?\b|\blate\b|\bslip(?:s|ped|page)?\b(?![- ](?:on|joint|blind|ring|plate|type))"
    r"|\bmilestones?\b|\b(?:completion|delivery|handover|start[- ]?up|target|due)\s+dates?\b|\bbehind\s+(?:schedule|plan|programme|program)\b"
    r"|\bpush(?:es|ed|ing)?\s+(?:back|out)\b|\bpush(?:es|ed|ing)?\s+(?:the|our|its)\s+[\w\s-]{0,30}?\bdates?\b"
    r"|\bpostpon\w*|\baccelerat\w*\s+(?:the\s+)?(?:work|works|schedule|programme|program|delivery|completion)\b"
    r"|\b\d+\s*(?:-\s*)?(?:days?|weeks?|months?)\b|\bschedule\b(?!\s*(?:[A-H]\b|[A-H]-?\d|\d|XS\b|XXS\b|STD\b))(?<!pipe schedule)"
    # a technical LIST called a schedule ("Coating Schedule", "valve schedule") is not time (builder H's replay of #1992, row 16)
    r"(?<!coating schedule)(?<!painting schedule)(?<!paint schedule)(?<!insulation schedule)(?<!line schedule)(?<!valve schedule)(?<!equipment schedule)(?<!cable schedule)(?<!lubrication schedule)(?<!inspection schedule)(?<!test schedule)(?<!testing schedule)(?<!maintenance schedule)(?<!material schedule)(?<!data schedule)(?<!drawing schedule)(?<!document schedule)(?<!instrument schedule)(?<!piping schedule)(?<!welding schedule)(?<!heat treatment schedule)(?<!pwht schedule)(?<!hydrotest schedule)"
)
_RAISES = re.compile(f"{_MONEY}|{_TIME}", re.IGNORECASE)


def raises_cost(question: str) -> bool:
    """True when the request holds any money or time word: the page then shows the HINT (and still offers the sentence). Runs of spaces
    and a hyphen between words read as one space first, so "coating-schedule" and "coating  schedule" meet the same exceptions (H)."""
    return bool(_RAISES.search(re.sub(r"(?<=\w)[\s-]+(?=\w)", " ", question or "")))


def offer(question: str, reply: str | None = None) -> dict[str, str | bool | None]:
    """What the page offers beside the draft: the set sentence, the hint when the request mentions money or time, and whether the reply
    ALREADY states a cost or schedule position (with its source), so the page says one cost / schedule message, never two (owner,
    27 Nov 2026: builder H's table, 6h and 6r)."""
    from .technical_query_reply_checks import states_cost

    speaks = states_cost(reply or "")
    return {"line": POSITION_LINE, "hint": HINT if raises_cost(question) and not speaks else None, "reply_speaks": speaks}
