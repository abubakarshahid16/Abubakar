"""The words of a failed check, from code's comparison only: the sentence a fail sends, every number read by code from the
verified quotes; and THE one decision "Not met, proven by code" (`proven_fail`)."""

from __future__ import annotations

from . import CONTRACTOR_FILLED, PROVISIONAL

#: The process note a paper-vs-paper comparison sentence carries (the AI chose the pairing). A card's "We ask" is read without it (the card's
#: own `proven` field says how the comment is proven); the stored comment and the team file's Comment cell keep it whole.
PAIRED_NOTE = " (the AI paired these two values; code compared them)"
#: What a failed check says of the stated figure, by the rule's operator.
_FAILS_AS = {
    "<=": ("is above", "limit"),
    "<": ("is not below", "limit"),
    ">=": ("is below", "minimum"),
    ">": ("is not above", "minimum"),
    "==": ("is not", "required value"),
    "!=": ("is", "excluded value"),
}


def _num(v) -> str:
    return f"{float(v):f}".rstrip("0").rstrip(".")


#: The same check worded as a QUESTION, for a provisional figure (it is never a finding that it fails).
_APPEARS = {
    "is above": "appears above",
    "is not below": "appears not below",
    "is below": "appears below",
    "is not above": "appears not above",
    "is not": "appears not to be",
    "is": "appears to be",
    "does not meet": "appears not to meet",
}


def _fails_comment(
    code_cmp: dict, quote: str, base: dict, asking: bool = False, firm: bool = False
) -> str:
    """The sent comment of a failed check (a provisional figure, or two paper values), every number from code's check of the
    verified quotes; the who-supplies note beside the figure when the quote has one."""
    from app import blank_markers

    (pv, pu), (rv, ru) = code_cmp["paper"], code_cmp["rule"]
    stated = f"{_num(pv)} {pu}".strip()
    rule = f"{_num(rv)} {ru}".strip()
    who = blank_markers.who_supplies(quote)
    if who:
        stated = f"{stated} ({who.lower()})"
    verb, noun = _FAILS_AS.get(str(code_cmp.get("op") or ""), ("does not meet", "rule"))
    verb, ask = (
        (_APPEARS.get(verb, verb), "please confirm")
        if asking
        else (verb, "contractor to confirm the value")
    )
    if code_cmp.get("read_from") == "verified paper quotes":
        # the AI chose which paper number is the other value: the sentence states both values and the page, no verdict
        page = code_cmp.get("limit_page")
        where = f"on page {page}" if page else "on this paper"
        # what the paper shows, with its page; the pairing is the AI's choice and says so (a guess is shown as a guess)
        return (
            f"The stated {stated} {verb} the {rule} stated {where}{PAIRED_NOTE}; {ask}."
        )
    if base.get("standard"):
        where = f"{base['standard']} clause {base['clause']}".strip()
    else:
        where = "the rule"
    if firm:
        return f"{PROVEN_FAIL}: the stated {stated} {verb} the {rule} {noun} of {where}; revise it to meet the rule."
    return f"The stated {stated} {verb} the {rule} {noun} of {where}; {ask}."


#: The words a fail proven by code opens with (`proven_fail`).
PROVEN_FAIL = "Not met, proven by code"


def proven_fail(label: str, code_cmp, deferred: bool, notes: list[str]) -> bool:
    """THE one decision "Not met, proven by code" (lead 4, owner's order of 18 Nov 2026): code compared the paper's VERIFIED
    quote with the HELD rule's verified words (`read_from` "verified quotes": both inputs are quotes) and the value breaks the
    limit. Never a value left open, never a provisional figure, never a figure filled in beside a who-supplies note (By
    Contractor), never the AI's words alone (no comparison, or a pairing of two paper values the AI chose)."""
    return (
        label == "Not met"
        and not deferred
        and isinstance(code_cmp, dict)
        and code_cmp.get("read_from") == "verified quotes"
        and code_cmp.get("result") == "fail"
        and not any(str(n).startswith((PROVISIONAL, CONTRACTOR_FILLED)) for n in notes)
    )
