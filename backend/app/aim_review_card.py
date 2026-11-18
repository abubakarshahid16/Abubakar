"""The comment CARD of the general review (planner 19:00, 18 Nov 2026; the target design BUILD/design/comment-card-design.html): for
every comment the page and the file show, a SEVERITY decided by CODE from the comment's points (never from its wording), a short
TITLE built from the checklist item or the field (no model call), and the parts PAPER SAYS / RULE SAYS / WE ASK / APPLIES TO as
separate fields, so the results page and the Excel lay the card out without parsing text.

Severity, most severe first (a comment takes its most severe point):
  "Must fix"            code's own verdict: the point is shown "Fail, compared by code" (a held rule's verified quote against
                        the paper's), never a provisional figure; an AI opinion beside a comparison is never "Must fix";
  "Check a value"       any other finding or question on a stated value: AI-judged, provisional, readers differ;
  "Missing information" the value is left open or blank (the run's own flag or mark), or found on no page;
  "Please confirm"      a confirmation (its own sheet and closed part of the page)."""

from __future__ import annotations

import re

from . import aim_review
from .aim_review import steps as _steps
from .aim_review_gate import AI_MARK
from .aim_review_store import FAIL_BY_CODE, PASS_BY_CODE

MUST_FIX, CHECK, MISSING, CONFIRM = (
    "Must fix",
    "Check a value",
    "Missing information",
    "Please confirm",
)
#: Most severe first: the order of the summary tiles and of a comment's points.
SEVERITIES = (MUST_FIX, CHECK, MISSING, CONFIRM)
#: The shown labels of code's own verdict: the only ones that are "compared by code".
BY_CODE = frozenset({FAIL_BY_CODE, PASS_BY_CODE})
#: A card title has fewer than this many words.
TITLE_WORDS = 12
KNOWLEDGE = "Engineering knowledge (no held rule book)"


def _parts(code_note) -> list[str]:
    return [x.strip() for x in str(code_note or "").split(";") if x.strip()]


def point_severity(p: dict) -> str:
    """The severity of ONE point, by code from its recorded state only."""
    parts = _parts(p.get("code_note"))
    provisional = any(x.startswith(aim_review.PROVISIONAL) for x in parts)
    if (
        p.get("shown_label") == FAIL_BY_CODE and not provisional
    ):  # code's own verdict only, never an AI opinion
        return MUST_FIX
    if (
        p.get("deferred")
        or p.get("ask") == "open"
        or any(x.startswith(_steps.NOT_ON_ANY_PAGE) for x in parts)
    ):
        return MISSING
    return CHECK


def title(p: dict) -> str:
    """A one-line title (fewer than `TITLE_WORDS` words) from the point's checklist item topic, else its field."""
    words = (
        str(p.get("topic") or p.get("field") or "Comment").replace("\n", " ").split()
    )
    short = " ".join(words[: TITLE_WORDS - 1]).strip(" .;:,")
    return short + (" ..." if len(words) >= TITLE_WORDS else "")


def rule_says(p: dict) -> str:
    """The rule a point rests on as the viewer may see it (a hidden book is already masked), with code's comparison when made."""
    if p.get("source") != "held standard":
        return KNOWLEDGE
    rule = " ".join(
        x for x in (p.get("standard"), p.get("clause") and f"clause {p['clause']}") if x
    )
    return (
        f"{rule}: {p['compared']}"
        if p.get("compared") and rule
        else (rule or p.get("compared") or "")
    )


def proven(members: list[dict]) -> str:
    """How the card is proven: by code only when code's own verdict (Pass or Fail, compared by code) stands on a point of it; an
    AI opinion beside a comparison (a paper pairing, a knowledge item, a comparison that could not run) is an AI reading."""
    return (
        "compared by code"
        if any(m.get("shown_label") in BY_CODE for m in members)
        else AI_MARK
    )


def card(comment: dict, members: list[dict], confirmation: bool = False) -> dict:
    """The card fields of one comment, from its member points (in line order)."""
    first = members[0]
    severity = (
        CONFIRM
        if confirmation
        else min((point_severity(m) for m in members), key=SEVERITIES.index)
    )
    return {
        "severity": severity,
        "title": title(first),
        "paper_says": comment.get("quote") or "",
        "rule_says": rule_says(first),
        "we_ask": (first.get("comment") or "").replace(_steps.PAIRED_NOTE, ""),
        "applies_to": [
            {
                "page": m.get("page"),
                "field": m.get("field") or "",
                "quote": m.get("quote") or "",
            }
            for m in members
        ],
        "proven": proven(members),
        "readers": readers_of(members),
    }


def add(
    comments: list[dict], confirmations: list[dict], points: list[dict]
) -> dict[str, int]:
    """Every comment and confirmation gets its card fields (in place). Returns the count per severity (the summary tiles)."""
    by_n = {p["n"]: p for p in points}
    counts = dict.fromkeys(SEVERITIES, 0)
    for group, confirm in ((comments, False), (confirmations, True)):
        for c in group:
            members = [by_n[n] for n in sorted(c.get("lines") or [c["n"]]) if n in by_n]
            c.update(card(c, members or [c], confirm))
            counts[c["severity"]] += 1
    return counts


#: The wording a run made before the readers moved out of the comment text: "To be checked: the two readers differ. First reader
#: (<label>): <the ask> Second reader (<label>): <reason>". Read back so an older run shows the same plain ask and tag.
_OLD_FRAME = re.compile(
    r"^To be checked: the two readers differ\.\s*First reader \((?P<first>[^)]*)\):\s*(?P<ask>.*?)(?:\s*Second reader \((?P<second>[^)]*)\):\s*(?P<why>.*))?$",
    re.DOTALL,
)
_NOTE = re.compile(
    r"readers differ: first (?P<first>[^,;]*), second (?P<second>[^:;]*)(?::\s*(?P<why>[^;]*))?"
)


def split_readers(
    comment: str, code_note, hidden: bool = False
) -> tuple[str, dict | None]:
    """(the comment's plain words, the readers' tag or None). A run made now keeps the first reader's plain ask as the comment and
    the readers in its code note; an older run's comment carried them in its text and is read back here. The tag: {"first", "second",
    "reason"}; for a line of a book the viewer may not open only {"first": "", "second": "", "reason": ""} (the words may hold rule
    words, rule 5)."""
    text = str(comment or "")
    old = _OLD_FRAME.match(text)
    found = _NOTE.search(str(code_note or ""))
    tag = None
    if old:
        text = old.group("ask").strip()
        tag = {
            "first": old.group("first") or "",
            "second": old.group("second") or "",
            "reason": (old.group("why") or "").strip(),
        }
    if found:
        tag = {
            "first": found.group("first").strip(),
            "second": found.group("second").strip(),
            "reason": (found.group("why") or "").strip(),
        }
    elif tag is None and "readers differ" in str(code_note or ""):
        tag = {"first": "", "second": "", "reason": ""}
    if tag is not None and hidden:
        tag = {"first": "", "second": "", "reason": ""}
    return text, tag


def readers_of(members: list[dict]) -> dict | None:
    """The tag of a card: the first member that carries one."""
    return next((m["readers"] for m in members if m.get("readers")), None)
