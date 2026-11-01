"""#1503 CRS export quality: what the sheet an engineer or a contractor reads
leaves out, merges and says plainly. EXPORT ONLY: no verdict, status, finding
or stored row changes; every function here works on the plain rows
`crs_export.build_crs_view` already has, and is reached only when
`CRS_EXPORT_QUALITY_ENABLED` is on (`meta["export_quality"]`).

Seven rules, each in one home (CLAUDE.md rule 8), all general for any document
(rule 13) - none looks at a layout, a filename or a document:

1. one row per (document, section, standard clause): a later DRAFT row on the
   same key is merged into the first row's comment (`merge_duplicates`); a
   row with an issued number, a safety tick or a carried-forward comment is
   never merged (each is its own thing an engineer or the contractor answers)
2. a row with no comment is dropped and counted (`drop_no_comment`)
3. every row names a page or says "page not found (<reason>)" (`page_cell`)
4. a comment is at most `COMMENT_LIMIT` characters; the rest moves to the AI
   Review Comments column (`split_comment`); Reasoning and Rule trust go to
   the Internal sheet, which the contractor copy does not have
5. the standards sheet lists Applied and Not in library only
6. "not in your library" says which kind of standard it is, by a prefix
   table (`standard_kind`): an unknown prefix stays a design standard
   (upload required), the claim the sheet made before
7. Priority is one of `PRIORITY_WORDS` (`priority_label`), never blank

No text is invented or reworded: merged, moved and cut text is the text the
row already had (numbers, units and clause references are kept whole - a cut
falls between words, never inside one).
"""

from __future__ import annotations

import re

from .rule_trust import UNPROVEN_REASON

COMMENT_LIMIT = 350

# ----------------------------------------------------------------- priority

PRIORITY_MISSING_VALUE = "Missing value"
PRIORITY_ENGINEER_TO_CHECK = "Engineer to check"
PRIORITY_FAIL = "Fail"
PRIORITY_PASS = "Pass"
#: The only words the Priority column may print with the switch on. No row of
#: the CRS is a pass today (a pass is no comment); the word is reserved.
PRIORITY_WORDS = (
    PRIORITY_MISSING_VALUE,
    PRIORITY_ENGINEER_TO_CHECK,
    PRIORITY_FAIL,
    PRIORITY_PASS,
)
#: crs_mapping's ranks: 1 out of limit, 2 missing value, 3 engineer to check.
_BY_RANK = {1: PRIORITY_FAIL, 2: PRIORITY_MISSING_VALUE, 3: PRIORITY_ENGINEER_TO_CHECK}


def priority_label(priority) -> str:
    """The fixed-list word for a rank. A rank outside 1-3 (an engineer's own
    comment, a carried-forward one, or none) is for a human to look at: it
    prints "Engineer to check", never a blank and never "None"."""
    rank = priority if isinstance(priority, int) and not isinstance(priority, bool) else None
    return _BY_RANK.get(rank, PRIORITY_ENGINEER_TO_CHECK)


# ------------------------------------------------------------ standard kind

KIND_DESIGN = "design"
KIND_MATERIAL = "material"
KIND_PURCHASING = "purchasing"

STATUS_BY_KIND = {
    KIND_DESIGN: "Not in your library - design standard (upload required)",
    KIND_MATERIAL: "Not in your library - material or product spec (reference only)",
    KIND_PURCHASING: "Not in your library - purchasing spec",
}
NOTE_BY_KIND = {
    KIND_DESIGN: "Standard not in your library - design standard (upload required)",
    KIND_MATERIAL: "Standard not in your library - material or product spec (reference only)",
    KIND_PURCHASING: "Standard not in your library - purchasing spec",
}

# Purchasing / materials specifications of an owner's system: "01-SAMSS-016".
_PURCHASING = re.compile(r"\bSAMSS\b", re.I)
# Material and product standards: ASTM (every ASTM number is a material,
# product or test spec), ASME SA-/SB- material numbers, ASME B16.x / B1.x /
# B18.x product-dimension standards. Other ASME numbers (B31, BPVC) are design.
_MATERIAL = re.compile(
    r"^\s*(?:ASTM\b|ASME\s*S[AB][\s-]?\d|ASME\s*B\s*(?:16|1|18|36)\.\d)", re.I
)


def standard_kind(reference: str) -> str:
    """Which kind of standard a reference names, from its prefix alone.
    Anything not recognised is a design standard - the same "upload required"
    claim the sheet made for every missing standard before this table."""
    text = str(reference or "")
    if _PURCHASING.search(text):
        return KIND_PURCHASING
    if _MATERIAL.search(text):
        return KIND_MATERIAL
    return KIND_DESIGN


def not_in_library_status(reference: str) -> str:
    return STATUS_BY_KIND[standard_kind(reference)]


def not_in_library_note(reference: str, default: str) -> str:
    return NOTE_BY_KIND[standard_kind(reference)] if reference else default


# --------------------------------------------------------------------- page

_HAS_PAGE = re.compile(r"(?<![A-Za-z])(?:pp?|pages?)\.?\s*\d", re.I)
NOT_FOUND = "page not found"
REASON_NOT_READ = "not read"
REASON_NOT_IDENTIFIED = "not identified"
REASON_OTHER_DOCUMENT = "needs other document"
#: row kinds whose page lives in a document the library does not hold
_OTHER_DOCUMENT_KINDS = ("standard_not_cited", "requires_other_document", "missing_reference")


def has_page(page_section: str) -> bool:
    return bool(_HAS_PAGE.search(str(page_section or "")))


def page_cell(page_section: str, row_kind: str = "") -> str:
    """The Page No./Section cell: as it was when it names a page, else
    "page not found (<reason>)" followed by whatever the cell said."""
    text = str(page_section or "").strip()
    if has_page(text):
        return text
    if text.lower().startswith("not read from"):
        reason = REASON_NOT_READ
    elif row_kind in _OTHER_DOCUMENT_KINDS:
        reason = REASON_OTHER_DOCUMENT
    else:
        reason = REASON_NOT_IDENTIFIED
    head = f"{NOT_FOUND} ({reason})"
    return f"{head} - {text}" if text else head


# ------------------------------------------------------------------ comment


def split_comment(text: str, limit: int = COMMENT_LIMIT) -> tuple[str, str]:
    """(head, rest): head is at most `limit` characters, cut at the last line
    end, sentence end or space before the limit (inside a word only when the
    text has no break at all); head + rest is the whole text."""
    text = str(text or "")
    if len(text) <= limit:
        return text, ""
    cut = 0
    for marker, keep in (("\n", 0), (". ", 1), (" ", 0)):
        at = text.rfind(marker, 0, limit + 1)
        if at > 0:
            cut = at + keep
            break
    if cut <= 0:
        cut = limit
    return text[:cut].rstrip(), text[cut:].lstrip()


def strip_unproven_flag(text: str) -> tuple[str, bool]:
    """Rule 4: the "(the rule is not yet proven: ...)" sentence the rule trust
    step appends to a datasheet comment is internal. Returns (text without it,
    whether it was there); the Internal sheet keeps it beside the row."""
    flag = f" ({UNPROVEN_REASON})"
    if flag not in text:
        return text, False
    return text.replace(flag, "").strip(), True


def move_overflow(ai_text: str, rest: str) -> str:
    """The AI Review Comments cell with the comment's overflow appended."""
    note = f"Continued from the comment: {rest}"
    return f"{ai_text}\n\n{note}" if ai_text else note


# --------------------------------------------------------------------- rows

#: rows that are never merged: a tick an engineer answers one by one, and a
#: comment carried from an earlier review under its own number
_NEVER_MERGED = ("safety_tick", "carried_forward")
_DRAFT = "Draft (not issued)"


def _issued(row: dict) -> bool:
    return bool(row.get("crs_ref")) and str(row.get("crs_status") or "") != _DRAFT


def _key(row: dict):
    section = str(row.get("page_section") or "").strip()
    clause = str(row.get("standard_reference") or "").strip()
    if not section or not clause:
        return None
    if row.get("row_kind") in _NEVER_MERGED or _issued(row):
        return None
    return (
        str(row.get("document_name") or ""),
        section,
        clause,
        row.get("engineer_confirmed") is True,
    )


def _join(first: str, later: str) -> str:
    first, later = str(first or ""), str(later or "")
    if not later or later in first:
        return first
    return f"{first}\n\n{later}" if first else later


def merge_duplicates(rows: list[dict]) -> tuple[list[dict], int]:
    """Rule 1. Returns (rows, number of rows merged away). The first row of a
    key keeps its place, number and kind; a later one adds its comment (and
    its reasoning and AI wording) after it and lends it a stronger rank."""
    out: list[dict] = []
    first_of: dict = {}
    merged = 0
    for row in rows:
        key = _key(row)
        if key is None or key not in first_of:
            copy = dict(row)
            out.append(copy)
            if key is not None:
                first_of[key] = copy
            continue
        base = first_of[key]
        for field in ("comment", "reasoning", "ai_review_comment", "rule_trust"):
            if field in row or field in base:
                base[field] = _join(base.get(field), row.get(field))
        ranks = [
            r
            for r in (base.get("priority"), row.get("priority"))
            if isinstance(r, int) and not isinstance(r, bool)
        ]
        if ranks:
            base["priority"] = min(ranks)
        merged += 1
    return out, merged


def drop_no_comment(rows: list[dict], has_no_text) -> tuple[list[dict], int]:
    """Rule 2 (internal copy; the contractor copy already withholds these).
    A row an engineer confirmed is kept: its number was issued, and the issue
    gate asks the engineer to write it again."""
    kept = [r for r in rows if r.get("engineer_confirmed") is True or not has_no_text(r)]
    return kept, len(rows) - len(kept)


def split_standards(standards: list[dict], considered_status: str) -> tuple[list[dict], list[dict]]:
    """Rule 5: (applied + not in library, considered not applied)."""
    shown = [s for s in standards if s.get("status") != considered_status]
    held_back = [s for s in standards if s.get("status") == considered_status]
    return shown, held_back
