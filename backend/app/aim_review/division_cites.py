"""THE DESIGN CODE'S DIVISION, CHECKED BY CODE (update 14, behind `updates.u13`; lead-4's row-4 list, builder H). A standard split into
DIVISIONS gives alternative rule sets for the same thing: a paper designed to one division should not take a clause from another
division of the same standard (u6 vessel #35, an AI opinion that code can decide). Code reads, from the paper's own lines:

  * the DECLARED design code: a line labelled "design code", "construction code" or "code of construction" that names a standard
    with a division ("<standard> [Section <n>] Div. <n>"), or the line right after such a label (a form's label and its value);
  * every OTHER line naming the same standard (and section) with a DIFFERENT division.

Each other division is one Question with both quotes, each a line of the paper found on its page: code proves the paper names two
divisions of one standard, not which one is right, so the contractor is asked to confirm (never Pass or Fail). Parts and sections
are complementary, never alternatives (a vessel code cites its welding and testing sections), so only a division is compared. A
line that states a division is NOT used ("not applicable", "not used", "excluded") is no citation. Code only: no model, no network.
"""

from __future__ import annotations

import re

ITEM_ID = "X-DIV"
TOPIC = "design code division"
_ROMAN = {"I": "1", "II": "2", "III": "3"}
#: A standard (an organisation in capitals and its number words), an optional section, then its division.
_CITE = re.compile(
    r"(?P<std>\b[A-Z]{2,6}(?:[ \-/](?:BPVC|[A-Z]{0,3}\d[\w.]*|[IVX]{1,4}))*)\s*,?\s*"
    r"(?:(?:Section|Sec\.?)\s*(?P<sec>[IVX]{1,4}|\d{1,2})\s*,?\s*)?"
    r"(?:Division|Div\.?)\s*(?P<div>[1-3]|III|II|I)\b"
)
_DECLARED = re.compile(
    r"(?i)\b(?:design|construction)\s+code\b|\bcode\s+of\s+construction\b"
)
_NOT_USED = re.compile(
    r"(?i)\bnot\s+(?:applicable|used|applied)\b|\bexcluded\b|\bn/?a\b"
)


def _key(m: re.Match) -> tuple[str, str]:
    """(the standard with its section, the division), normalised: "ASME VIII" and "ASME Section VIII" are one standard."""
    std = " ".join(t for t in re.split(r"[ \-/]+", m.group("std")) if t and t != "BPVC")
    sec = m.group("sec") or ""
    div = _ROMAN.get(m.group("div"), m.group("div"))
    return (f"{std} {sec}".strip().upper(), div)


def _cites(pages: dict) -> list[tuple[int, str, tuple[str, str], bool]]:
    """(page, the whole line, (standard, division), is it the declared design code) for every division citation of the paper."""
    out = []
    for page in sorted(pages):
        label_before = False  # a form prints the label on one line and its value on the next ("Design code" / "<standard> Div. 1")
        for line in str(pages.get(page) or "").splitlines():
            text = " ".join(line.split())
            if not text:
                continue
            found = list(_CITE.finditer(text))
            declared = bool(_DECLARED.search(text)) or label_before
            label_before = bool(_DECLARED.search(text)) and not found
            if _NOT_USED.search(text):
                continue
            for m in found:
                out.append((page, text[:300], _key(m), declared))
    return out


def lines(paper) -> list[dict]:
    """The Questions: one per other division of the declared design code's standard that the paper cites."""
    cites = _cites(getattr(paper, "pages", {}) or {})
    declared = next((c for c in cites if c[3]), None)
    if declared is None:
        return []
    page, quote, (std, div), _ = declared
    out, seen = [], set()
    for p, other, (s, d), is_declared in cites:
        if is_declared or s != std or d == div or d in seen:
            continue
        seen.add(d)
        out.append(
            {
                "item_id": ITEM_ID,
                "finding_no": len(out) + 1,
                "label": "Question",
                "field": TOPIC,
                "page": page,
                "quote": quote,
                "comment": (
                    f"The paper states its design code as {std} Division {div} (page {page}), but cites {std} Division {d} "
                    f'on page {p}: "{other}". The two divisions are alternative rules; please confirm which division applies '
                    "and correct the paper."
                ),
                "standard": "",
                "book_document_id": "",
                "clause": "",
                "source": "not from a held standard",
                "topic": TOPIC,
                "code": f"code read both lines of the paper: design code {std} Division {div} (page {page}); "
                f"{std} Division {d} cited on page {p}",
                "numbers": None,
                "code_compare": None,
                "deferred": False,
                "ask": "",
            }
        )
    return out


def add_lines(paper, state) -> None:
    """Add the Questions to the run (`state.decided`). A fault is a step that did not run: recorded on the run, the review goes on."""
    try:
        state.decided += lines(paper)
    except Exception as exc:  # noqa: BLE001 - never stops a finished review: recorded as a step that did not run
        from . import faults

        faults.record("aim_division_check", "the design code division check", exc)
