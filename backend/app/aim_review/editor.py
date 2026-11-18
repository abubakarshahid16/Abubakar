"""S5, the editor of the general review's comment sheet (order 14): ONE call per paper after the judge, which may only take a
sent line off the sheet; code checks every move. A "paper states otherwise" move follows the strict E1 rule for every kind of
paper (`_contradicted`); a looser rule for procedures (K2) was tried and dropped (light check 9dee5805; the record of what was
tried is kept as skipped tests in tests/test_aim_method_scope.py)."""

from __future__ import annotations

import logging
import re

from . import EDITED, PROVISIONAL, PROVISIONAL_FAILS
from . import prompts as P
from .engine import StepFailed
from .steps import NOT_ON_ANY_PAGE, _dumps, paper_block
from .verify import norm, quote_in

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ S5: the editor (it may only take a comment off the sheet)

REPEATS, CONTRADICTED = "repeats", "paper_states_otherwise"
#: Room for the editor's COMPACT answer on a big sheet (a valve run: 125 sent lines; 4000 ended the answer at the limit).
EDIT_MAX_TOKENS = 16000
#: At most this many sent lines per editor call; more go to a SECOND call (at most two calls, the same step, the run meter).
EDIT_CHUNK = 80
#: What the run's calls say when an editor answer was not applied (`CallRecord`, no model, no cost).
NOT_APPLIED = "editor not applied"


def s5_edit(model, paper, lines: list[dict], lead: str) -> int:
    """ONE call per paper after S4 (TWO when the sent lines exceed EDIT_CHUNK): the editor sees the SENT lines only (n = the
    line's number, field, page, comment, quote) and the paper, and may only take a line off the comment sheet (`_edit_reason`)
    or group lines that make the same point (`_accept_groups`); code checks every move and every group. A code-proven failure is
    never offered. Each call's answer is applied WHOLE or not at all: a failed or cut call (the answer too long) applies
    nothing and the run's calls say so. A group never spans the two calls. Returns the number of lines moved."""
    from . import sendable
    from .engine import to_line

    sent = {n: d for n, d in enumerate(lines, 1) if sendable(to_line(n, d))}
    # a line code compared and found failing is code's decision: never offered to the editor, never movable (light check E1)
    offered = {n: d for n, d in sent.items() if not _code_failed(d)}
    keys = list(offered)
    half = -(-len(keys) // 2)
    parts = [keys] if len(keys) <= EDIT_CHUNK else [keys[:half], keys[half:]]
    moved = 0
    for part in (p for p in parts if p):
        out = _ask(model, paper, {n: offered[n] for n in part}, lead)
        if out is not None:
            moved += _apply(out, {n: offered[n] for n in part}, offered, sent, paper)
    return moved


def _ask(model, paper, shown_lines: dict, lead: str) -> dict | None:
    """One editor call on these lines; None (and a line in the run's calls) when it failed or its answer was cut."""
    shown = [
        {"n": n, "field": d.get("field") or "", "page": d.get("page"), "comment": d.get("comment") or "", "quote": d.get("quote") or ""}
        for n, d in shown_lines.items()
    ]  # fmt: skip
    carries = {paper.paper_id} | {
        str(d["book_document_id"])
        for d in shown_lines.values()
        if d.get("book_document_id")
    }
    try:
        out = model.ask(
            step="aim_edit",
            model=lead,
            system="",
            cached=paper_block(paper),
            prompt=P.EDIT_TASK % {"comments": "\n".join(_dumps(x) for x in shown)},
            carries=carries,
            max_tokens=EDIT_MAX_TOKENS,
        )
    except (
        StepFailed
    ) as exc:  # nothing of a failed or cut answer is applied; the run's calls say why
        code = str(exc).split(":", 1)[-1].strip().split(" ", 1)[0]
        why = "answer too long" if code == "stop_max_tokens" else code
        _note(model, f"{NOT_APPLIED}: {why}")
        log.info("general review: the editor answer was not applied (%s)", code)
        return None
    return out if isinstance(out, dict) else None


def _note(model, words: str) -> None:
    """A row of the run's calls with no model and no cost: what happened to the editor's answer."""
    from .engine import CallRecord

    meter = getattr(model, "meter", None)
    if meter is not None and hasattr(meter, "calls"):
        meter.calls.append(
            CallRecord(
                step="aim_edit", model="code", prompt_chars=0, ok=False, code=words
            )
        )


def _apply(out: dict, part: dict, offered: dict, sent: dict, paper) -> int:
    """One call's answer, whole, under code's checks: its moves, then its groups; only lines of THIS call (`part`)."""
    moves = out.get("moves")
    moved = 0
    for mv in moves if isinstance(moves, list) else []:
        n = mv.get("n") if isinstance(mv, dict) else None
        why = (
            _edit_reason(mv, n, part, sent, paper)
            if isinstance(n, int) and n in part
            else None
        )
        if why:
            d = part.pop(n)
            offered.pop(n, None)
            sent.pop(n)
            d["code"] = "; ".join(x for x in (d.get("code"), f"{EDITED}: {why}") if x)
            moved += 1
    groups = out.get("groups")
    _accept_groups(groups if isinstance(groups, list) else [], part)
    return moved


#: The code-note part that marks the lines the editor grouped as ONE point (`aim_review_view.group_comments` reads it): every
#: member carries "same point as line <the group's first line>".
SAME_POINT = "same point as line"


def _accept_groups(groups: list, offered: dict) -> int:
    """The editor's GROUPS of sent lines that make the same point (the owner's "one comment per point, listing every sheet and
    page"), checked by code: every member is a real line still offered (sent, not moved, never a code failure); at least two;
    the SAME shown label (a Fail never joins a Question); the same compare kind; no line in two groups (a later group that
    overlaps is refused). An accepted group marks each member's code note; nothing is added, rewritten or relabelled. Returns
    the number of groups accepted."""
    from app.aim_review_store import shown_label

    taken: set[int] = set()
    accepted = 0
    for g in groups:
        if not isinstance(g, list) or not all(
            isinstance(n, int) and not isinstance(n, bool) for n in g
        ):
            continue
        members = sorted(set(g))
        if len(members) < 2 or any(n not in offered or n in taken for n in members):
            continue
        lines = [offered[n] for n in members]
        shown = {
            shown_label(
                d.get("label") or "",
                d.get("code_compare"),
                bool(d.get("deferred")),
                d.get("code") or "",
            )
            for d in lines
        }
        kinds = {
            (d.get("code_compare") or {}).get("read_from")
            if isinstance(d.get("code_compare"), dict)
            else None
            for d in lines
        }
        if len(shown) != 1 or len(kinds) != 1:
            continue
        for d in lines:
            d["code"] = "; ".join(
                x for x in (d.get("code"), f"{SAME_POINT} {members[0]}") if x
            )
        taken |= set(members)
        accepted += 1
    return accepted


def _code_failed(d: dict) -> bool:
    """Code compared this line and it FAILED (a rule compare, a provisional figure, a paper compare)."""
    cmp_ = d.get("code_compare")
    parts = {x.strip() for x in str(d.get("code") or "").split(";")}
    return (
        isinstance(cmp_, dict) and cmp_.get("result") == "fail"
    ) or PROVISIONAL_FAILS in parts


#: What a line's own words say when its claim is "not stated / missing" (read by code from the line, never from the editor).
_SAYS_MISSING = re.compile(
    r"\b(?:not\s+(?:stated|given|shown|provided|specified|indicated|found|listed|mentioned|filled)"
    r"|(?:is|are|was|left)\s+(?:blank|empty|missing)|missing|absent|no\s+(?:value|entry|figure|data)\b"
    r"|does\s+not\s+(?:state|show|give|specify|list|mention)|do(?:es)?\s+not\s+appear)",
    re.IGNORECASE,
)


def _claims_missing(d: dict) -> bool:
    """The line's own claim is that something is not stated: a Question or an AI opinion whose code note is "not on any page" or
    "no paper quote", or whose comment says so."""
    if d.get("label") not in ("Question", "AI opinion"):
        return False
    code = str(d.get("code") or "")
    return (
        NOT_ON_ANY_PAGE in code
        or "no paper quote" in code
        or bool(_SAYS_MISSING.search(str(d.get("comment") or "")))
    )


def _states_value(quote: str, field: str) -> bool:
    """The quote holds the line's field label (folded) followed by a value: not empty, not a blank or deferral form."""
    from app import blank_markers

    label, q = norm(field), norm(quote)
    at = q.find(label) if label else -1
    if at < 0:
        return False
    value = q[at + len(label) :].lstrip(" :=-")
    if not re.search(r"[a-z0-9]", value):
        return False
    blank, _marker = blank_markers.classify(value)
    return not (blank or blank_markers.is_whole_deferral(value, value_field=True))


def _same_place(a: dict, b: dict) -> bool:
    """Two lines about the same place: the same page AND the same verified quote or the same compared value."""
    if a.get("page") is None or a.get("page") != b.get("page"):
        return False
    qa, qb = norm(a.get("quote") or ""), norm(b.get("quote") or "")
    if qa and qa == qb:
        return True
    ca, cb = a.get("code_compare"), b.get("code_compare")
    return (
        isinstance(ca, dict)
        and isinstance(cb, dict)
        and ca.get("paper") is not None
        and ca.get("paper") == cb.get("paper")
    )


def _edit_reason(mv: dict, n: int, offered: dict, sent: dict, paper) -> str | None:
    """Code's check of one move of an OFFERED line (never a code-proven failure): the reason words, or None (refused: the line
    stays sent). "repeats": line `of` is real, sent, not this line, and about the same place (`_same_place`). "paper states
    otherwise": the strict E1 rule for every kind of paper (`_contradicted`)."""
    d = offered[n]
    if mv.get("reason") == REPEATS:
        m = mv.get("of")
        if not isinstance(m, int) or m == n or m not in sent:
            return None
        return f"repeats line {m}" if _same_place(d, sent[m]) else None
    if mv.get("reason") == CONTRADICTED:
        return _contradicted(d, str(mv.get("quote") or ""), mv.get("page"), paper)
    return None


def _never_moved(d: dict) -> bool:
    """A line that is never taken off as "paper states otherwise": one code compared (any result), a value the vendor left open
    (deferred), or a provisional figure (any provisional note)."""
    parts = {x.strip().split(":", 1)[0] for x in str(d.get("code") or "").split(";")}
    return (
        isinstance(d.get("code_compare"), dict)
        or bool(d.get("deferred"))
        or any(x.startswith(PROVISIONAL) for x in parts)
    )


def _contradicted(d: dict, quote: str, named_page, paper) -> str | None:
    """THE STRICT E1 RULE, for every kind of paper (light check 9dee5805: a looser rule could not prove the quote answers the
    claim; the third round, so rethought): the line claims a value is not stated (`_claims_missing`); it is not a line code
    compared, deferred or provisional (`_never_moved`); the quote has no "..." part; code finds it on the line's OWN page (the
    editor's page only when the line has none) and it holds the line's field label followed by a value (`_states_value`). The
    reason says exactly what code checked."""
    if _never_moved(d) or not _claims_missing(d) or "..." in quote or "\u2026" in quote:
        return None
    page = d.get("page") if d.get("page") is not None else named_page
    if not isinstance(page, int):
        return None
    if not quote_in(quote, paper.pages.get(page, "")) or not _states_value(
        quote, str(d.get("field") or "")
    ):
        return None
    return f'the paper gives a value for this field on page {page}: "{quote[:200]}"'
