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
3. every row names a page or says "page not found (<reason>)" (`page_cell`); with
   CRS_PAGE_CELL_FIELD_ENABLED it says the section or field instead (`no_page_cell`)
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

#1503 remainder, CRS_EXPORT_QUALITY_STRICT_ENABLED (needs the switch above, off by
default): rows with no page merge on one clause when their printed reason is the
same (`_strict_key`; a safety tick stays its own row), a comment that was only the "not
yet proven" flag counts as no comment (`_clear_flag_only`), the prefix table reads
the other spellings `standard_ids` accepts (`_MATERIAL_WIDE`), and the screen gets
the Internal sheet (`internal_preview`).
"""

from __future__ import annotations

import re

from openpyxl.styles import Alignment, Font

from . import crs_page_words
from .config import settings
from .crs_mapping import NOTE_MISSING_STANDARD
from .rule_trust import UNPROVEN_REASON

AI_COLUMN = "AI Review Comments"  # crs_export.AI_COLUMN
COMMENT_LIMIT = 350
#: Internal-only content (Reasoning, Rule trust, the standards considered and
#: not applied): never in the contractor copy.
INTERNAL_SHEET = "Internal"
INTERNAL_ROW_COLUMNS = (
    "Item No",
    "Row ref",
    "Reasoning (internal)",
    "Rule trust (internal)",
)
INTERNAL_CONSIDERED_COLUMNS = (
    "Standard considered, not applied",
    "Status",
    "Method",
    "Reason",
)

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
    rank = (
        priority
        if isinstance(priority, int) and not isinstance(priority, bool)
        else None
    )
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
#: The same families in every spelling `standard_ids` reads ("ASME-B16-47",
#: "ANSI B16.5", "ANSI/ASME SA-105"), and an ASTM number cited bare WITH its grade
#: ("A193 Gr B7"): a bare letter and number alone ("A193", "B2000") could be anything,
#: so it stays a design standard, the claim the sheet makes for anything unknown.
_MATERIAL_WIDE = re.compile(
    r"^\s*(?:ASTM\b"
    r"|(?:ANSI\s*/\s*)?(?:ASME|ANSI)(?:\s*/\s*ANSI)?[-\s]*"
    r"(?:S[AB][-\s]?\d|B[-\s]*(?:16|1|18|36)[-._ ]\d)"
    r"|[AB][-\s]?\d{2,4}(?![\d.])[\s,/-]*(?:Gr\.?|Grade)(?![A-Za-z]))",
    re.I,
)


def one_row_enabled() -> bool:
    """CRS_ONE_ROW_PER_PROBLEM_ENABLED (`crs_one_row`): the sheet is merged where it is
    composed, on the owner's identity, so this view merges nothing more."""
    return bool(settings.crs_one_row_per_problem_enabled)


def strict_enabled() -> bool:
    """CRS_EXPORT_QUALITY_STRICT_ENABLED (default off). It acts only where
    `CRS_EXPORT_QUALITY_ENABLED` already holds: every reader here is reached
    from `prepare` or `finish`, which that switch guards."""
    return bool(settings.crs_export_quality_strict_enabled)


def standard_kind(reference: str) -> str:
    """Which kind of standard a reference names, from its prefix alone.
    Anything not recognised is a design standard - the same "upload required"
    claim the sheet made for every missing standard before this table."""
    text = str(reference or "")
    if _PURCHASING.search(text):
        return KIND_PURCHASING
    if _MATERIAL.search(text) or (strict_enabled() and _MATERIAL_WIDE.search(text)):
        return KIND_MATERIAL
    return KIND_DESIGN


def not_in_library_status(reference: str) -> str:
    return STATUS_BY_KIND[standard_kind(reference)]


def not_in_library_note(reference: str, default: str) -> str:
    return NOTE_BY_KIND[standard_kind(reference)] if reference else default


# --------------------------------------------------------------------- page

# "p.2", "pp. 3-4", "page 5": the word "page" or "p." WITH its separator. A bare
# "P101" or "P2" is an equipment tag, not a page.
_HAS_PAGE = re.compile(r"(?<![A-Za-z0-9])(?:pp?\.\s*|pages?\s+)\d", re.I)
NOT_FOUND = "page not found"
REASON_NOT_READ = "not read"
REASON_NOT_IDENTIFIED = "not identified"
REASON_OTHER_DOCUMENT = "needs other document"
#: row kinds whose page lives in a document the library does not hold
_OTHER_DOCUMENT_KINDS = (
    "standard_not_cited",
    "requires_other_document",
    "missing_reference",
)


#: Every cell of `no_page_cell` ends with this: a row with no verified quote has no page.
NO_PAGE = "so no page"
#: A row about a standard the submittal does or does not cite, with no finding behind it:
#: there is no quote by construction, and it needs no other document.
_NOT_CITED = "standard_not_cited"
_NOT_APPLICABLE = "standard_not_applicable"


def has_page(page_section: str) -> bool:
    return bool(_HAS_PAGE.search(str(page_section or "")))


def no_page_cell(text: str, row_kind: str, standard: str) -> str:
    """The cell of a row with no page: the section or field it is about, and why there
    is no page. A page comes only from a verified quote (`crs_mapping._page_section`), so
    a row with none has no page to print; none is looked for or guessed here."""
    field = crs_page_words.field_first(text)
    if field:
        return f"{field}, {NO_PAGE}"
    if row_kind == _NOT_CITED and standard:
        return f"Whole submittal: {standard} is not cited, {NO_PAGE}"
    about = f"About {standard}" if standard else "No section or field recorded"
    head = f"Section: {text}" if text else about
    if row_kind == _NOT_APPLICABLE and standard and not text:
        head = f"Whole submittal: about {standard}"
    if row_kind in _OTHER_DOCUMENT_KINDS:
        return f"{head}: another document is needed, {NO_PAGE}"
    return f"{head}: no verified quote, {NO_PAGE}"


def page_cell(page_section: str, row_kind: str = "", standard: str = "") -> str:
    """The Page No./Section cell: as it was when it names a page, else
    "page not found (<reason>)" followed by whatever the cell said; with
    CRS_PAGE_CELL_FIELD_ENABLED, `no_page_cell`."""
    text = str(page_section or "").strip()
    if has_page(text):
        return text
    if settings.crs_page_cell_field_enabled:
        return no_page_cell(text, row_kind, standard)
    if text.lower().startswith("not read from"):
        reason = REASON_NOT_READ
    elif row_kind in _OTHER_DOCUMENT_KINDS:
        reason = REASON_OTHER_DOCUMENT
    else:
        reason = REASON_NOT_IDENTIFIED
    head = f"{NOT_FOUND} ({reason})"
    return f"{head} - {text}" if text else head


# ------------------------------------------------------------------ comment


_UNIT_LEADERS = (
    "clause",
    "cl.",
    "section",
    "sec.",
    "para",
    "paragraph",
    "item",
    "no.",
    "table",
    "figure",
)
_SENTENCE_END = re.compile(r"(?<=[.!?])[ \t]+(?=[A-Z(\"'])|\n+")
_ACTION = re.compile(
    r"\b(?:contractor to|engineer to|requested|please|to confirm|to clarify|to correct|"
    r"to provide|to submit|to state)\b",
    re.I,
)


def _bad_space(text: str, at: int) -> bool:
    """Is the space at `at` between a number and its unit, or a clause word and
    its id? A cut there would part "10" from "mm" or "clause" from "4.1"."""
    before = text[:at].split(" ")[-1]
    after = text[at + 1 :].split(" ")[0]
    if any(ch.isdigit() for ch in before) and after[:1] and not after[:1].isupper():
        return True
    return before.lower() in _UNIT_LEADERS and any(ch.isdigit() for ch in after)


def split_comment(text: str, limit: int = COMMENT_LIMIT) -> tuple[str, str]:
    """(head, rest): head is at most `limit` characters, cut at the last line
    end, sentence end or space before the limit (never between a number and its
    unit or a clause word and its id; inside a word only when the text has no
    break at all); head + rest is the whole text."""
    text = str(text or "")
    if len(text) <= limit:
        return text, ""
    cut = 0
    for marker, keep in (("\n", 0), (". ", 1), (" ", 0)):
        at = text.rfind(marker, 0, limit + 1)
        while at > 0 and marker == " " and _bad_space(text, at):
            at = text.rfind(marker, 0, at)
        if at > 0:
            cut = at + keep
            break
    if cut <= 0:
        cut = limit
    return text[:cut].rstrip(), text[cut:].lstrip()


def shorten(text: str, limit: int = COMMENT_LIMIT) -> tuple[str, str]:
    """`split_comment` that keeps the requested action in the comment: the last
    sentence that asks the contractor for something stays after the leading
    sentences that fit; the sentences left out are the rest (nothing is lost)."""
    text = str(text or "")
    if len(text) <= limit:
        return text, ""
    parts, seps, last = [], [], 0
    for m in _SENTENCE_END.finditer(text):
        parts.append(text[last : m.start()])
        seps.append(m.group())
        last = m.end()
    parts.append(text[last:])
    seps.append("")
    action = [i for i, p in enumerate(parts) if i > 0 and _ACTION.search(p)]
    if not action or len(parts[action[-1]]) >= limit:
        return split_comment(text, limit)
    k = action[-1]
    budget, taken = limit - len(parts[k]) - 1, 0
    for i in range(k):
        if taken + len(parts[i]) + len(seps[i]) > budget:
            break
        taken += len(parts[i]) + len(seps[i])
        last_taken = i
    else:
        last_taken = k - 1
    head_i = range(0, last_taken + 1) if taken else range(0)
    head = "".join(parts[i] + seps[i] for i in head_i) + parts[k]
    skipped = [i for i in range(len(parts)) if i not in head_i and i != k]
    rest = "".join(parts[i] + seps[i] for i in skipped).strip()
    return (head, rest) if rest and len(head) <= limit else split_comment(text, limit)


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


def _strict_key(row: dict):
    """The key with the strict switch on: `_key`, except that a row with no page
    takes the reason it prints as its anchor, so the sheet cannot show two rows
    with one document, page cell and clause. Safety ticks, carried-forward and
    issued rows stay their own, as in `_key`: a merged tick would keep the first
    tick's reference, and confirming it would leave the other under a confirmed
    row."""
    clause = str(row.get("standard_reference") or "").strip()
    kind = row.get("row_kind") or ""
    if not clause or kind in _NEVER_MERGED or _issued(row):
        return None
    section = str(row.get("page_section") or "").strip()
    return (
        str(row.get("document_name") or ""),
        section or page_cell("", kind),
        row.get("engineer_confirmed") is True,
        clause,
    )


def _join(first: str, later: str) -> str:
    first, later = str(first or ""), str(later or "")
    if not later or later in first:
        return first
    return f"{first}\n\n{later}" if first else later


def merge_duplicates(rows: list[dict], key_of=_key) -> tuple[list[dict], int]:
    """Rule 1. Returns (rows, number of rows merged away). The first row of a
    key keeps its place, number, kind and fill; a later one adds its comment
    (and its reasoning and AI wording) after it. Only the RANK is lent: the
    row prints the strongest rank of the group (a Fail merged into an
    engineer's comment shows Fail), while its row kind and colour stay the
    first row's."""
    out: list[dict] = []
    first_of: dict = {}
    merged = 0
    for row in rows:
        key = key_of(row)
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
    kept = [
        r for r in rows if r.get("engineer_confirmed") is True or not has_no_text(r)
    ]
    return kept, len(rows) - len(kept)


def _clear_flag_only(rows: list[dict], copy: str) -> tuple[list[dict], int]:
    """A comment that was only the "not yet proven" flag is no comment: without
    it the cell would print blank. Internal copy: the row goes on as an empty one
    (`drop_no_comment` then drops it, or it prints the engineer sentence). Client
    copy: there is nothing to send, so it is left out, and `finish` counts it in
    `rows_withheld_no_text`, the count the client screen says aloud."""
    out: list[dict] = []
    dropped = 0
    for row in rows:
        text, gone = strip_unproven_flag(str(row.get("comment") or ""))
        if gone and not text:
            if copy != "internal":
                dropped += 1
                continue
            row = {**row, "comment": ""}
        out.append(row)
    return out, dropped


def split_standards(
    standards: list[dict], considered_status: str
) -> tuple[list[dict], list[dict]]:
    """Rule 5: (applied + not in library, considered not applied)."""
    shown = [s for s in standards if s.get("status") != considered_status]
    held_back = [s for s in standards if s.get("status") == considered_status]
    return shown, held_back


# ----------------------------------------------------------------- the view


def enabled() -> bool:
    """CRS_EXPORT_QUALITY_ENABLED (default off); a caller may override it in
    `meta["export_quality"]`."""
    return bool(settings.crs_export_quality_enabled)


#: `crs_mapping.safety_tick_text`'s words; a test holds them to what it writes.
TICK_LEAD = "ENGINEER TO TICK"
TICK_ACTION = "Read the clause and the value on the page and tick, or say what is off."


def ticked_words(row: dict) -> dict:
    """With CRS_PLAIN_NOTES_ENABLED, a safety row an engineer has really ticked says so,
    not that it waits (`crs_decider.tick_done`). An edited comment is not a tick: it may be
    an objection, so the engineer's words print first and the row still waits. On the view
    only: the words a number keeps (`crs_carry`) are not touched, so the next run's row is
    compared with what the engineer read."""
    if not settings.crs_plain_notes_enabled or row.get("row_kind") != "safety_tick":
        return row
    words = row.get("engineer_words")
    if words:
        return {**row, "comment": f"{words}\n{row.get('comment') or ''}"}
    if not row.get("tick_done"):
        return row
    said = str(row.get("comment") or "").replace(f" {TICK_ACTION}", "")
    return {**row, "comment": said.replace(TICK_LEAD, "TICKED BY ENGINEER", 1)}


def prepare(
    findings: list[dict], copy: str, has_no_text, on: bool
) -> tuple[list[dict], int, int]:
    """Rules 2 and 1, before the rows are built: (rows, dropped, merged);
    the rows untouched when the switch is off."""
    findings = [ticked_words(f) for f in findings]
    if not on:
        return findings, 0, 0
    strict = strict_enabled()
    dropped = 0
    if strict:
        findings, dropped = _clear_flag_only(findings, copy)
    if copy == "internal":
        findings, gone = drop_no_comment(findings, has_no_text)
        dropped += gone
    if one_row_enabled():
        return findings, dropped, 0
    findings, merged = merge_duplicates(findings, _strict_key if strict else _key)
    return findings, dropped, merged


def _note(note: str, count: int, detail: str) -> dict:
    return {"note": note, "standard": "", "count": count, "detail": detail}


def _finish_rows(rows: list[dict], ref_label: str) -> tuple[set[str], bool]:
    """Rules 3, 4 and 7 on each row: (rows that had the unproven flag,
    whether any comment overflowed into the AI column)."""
    flagged: set[str] = set()
    overflowed = False
    for entry in rows:
        for field in ("comment", "ai_review_comment"):
            entry[field], gone = strip_unproven_flag(entry[field])
            if gone:
                flagged.add(entry["row_ref"])
        entry["page_section"] = page_cell(
            entry["page_section"],
            entry.get("row_kind") or "",
            entry.get("standard_reference") or "",
        )
        entry["priority_label"] = priority_label(entry.get("priority"))
        if entry["comment_missing"]:
            continue
        first, _, tail = entry["comment"].partition("\n")
        prefix = first + "\n" if first.startswith(f"{ref_label}: ") and tail else ""
        head, rest = shorten(
            entry["comment"][len(prefix) :], COMMENT_LIMIT - len(prefix)
        )
        if rest:
            entry["comment"] = prefix + head
            entry["ai_review_comment"] = move_overflow(entry["ai_review_comment"], rest)
            overflowed = True
    return flagged, overflowed


def _internal_extras(
    view: dict, considered: list[dict], flagged: set[str], counts: tuple
):
    """The internal copy's notes and Internal-sheet content: (notes, sheet)."""
    dropped, merged = counts
    notes = [
        {**n, "note": not_in_library_note(n["standard"], n["note"])}
        if n["note"] == NOTE_MISSING_STANDARD
        else n
        for n in view["review_notes"]
    ]
    if dropped:
        notes.append(
            _note(
                "Rows dropped: no comment",
                dropped,
                "rows with no comment text are not exported",
            )
        )
    if merged:
        notes.append(
            _note(
                "Rows merged into an earlier row",
                merged,
                "same document, section and standard clause",
            )
        )
    if considered:
        notes.append(
            _note(
                "Standards considered, not applied",
                len(considered),
                "listed on the Internal sheet",
            )
        )
    rows = [
        {
            "item_no": e["item_no"],
            "row_ref": e["row_ref"],
            "reasoning": e["reasoning"],
            "rule_trust": e["rule_trust"]
            + (f" - {UNPROVEN_REASON}" if e["row_ref"] in flagged else ""),
        }
        for e in view["rows"]
        if e["reasoning"] or e["rule_trust"] or e["row_ref"] in flagged
    ]
    return notes, {"rows": rows, "considered": considered}


def finish(view: dict, dropped: int, merged: int) -> dict:
    """Rules 3 to 7 on the view `build_crs_view` made (switch on only)."""
    from . import crs_export as ce

    internal = view["crs_copy"] == ce.COPY_INTERNAL
    if not internal:  # a client copy has no Review notes: the withheld count says it
        view["rows_withheld_no_text"] += dropped
        dropped = 0
    flagged, overflowed = _finish_rows(view["rows"], ce.ROW_REF_LABEL)
    standards, considered = split_standards(
        view["applicable_standards"], ce.STATUS_CONSIDERED
    )
    for s in standards:
        if s["status"] == ce.STATUS_NOT_IN_LIBRARY:
            s["status"] = not_in_library_status(s["standard"])
    notes, inner = view["review_notes"], {}
    if internal:
        notes, inner = _internal_extras(view, considered, flagged, (dropped, merged))
    base = view["columns"][: len(ce.HEADERS) + 2]
    view.update(
        columns=base + ([ce.AI_COLUMN] if internal or overflowed else []),
        applicable_standards=standards,
        review_notes=notes,
        export_quality=True,
        internal_sheet=inner,
        internal_preview=inner if strict_enabled() else {},
        rows_dropped_no_comment=dropped,
        rows_merged=merged,
    )
    return view


def notice_height(view: dict) -> int:
    """The notice row's height. Off: as it was, whatever the length. With
    CRS_PLAIN_NOTES_ENABLED the notice names its parts, so its words must fit."""
    if not settings.crs_plain_notes_enabled:
        return 30
    return max(30, 15 * (len(view["incomplete_notice"]) // 110 + 1))


def tail_cells(view: dict, entry: dict, current: list) -> list:
    """The cells after Priority on a row. Switch off: `current`, the caller's
    own three columns. On: the AI column when this copy has it, else none."""
    if not view.get("export_quality"):
        return current
    return [entry["ai_review_comment"]] if view["columns"][-1] == AI_COLUMN else []


def write_internal_sheet(wb, inner: dict, write) -> None:
    """The Internal sheet: the reasoning and rule trust behind each row, then
    the standards considered and not applied. `write` is `crs_export._write`."""
    sheet = wb.create_sheet(INTERNAL_SHEET)
    wrap = Alignment(wrap_text=True, vertical="top")
    r = 1
    for col, header in enumerate(INTERNAL_ROW_COLUMNS, start=1):
        write(sheet, r, col, header).font = Font(bold=True)
    for entry in inner.get("rows", []):
        r += 1
        for col, key in enumerate(
            ("item_no", "row_ref", "reasoning", "rule_trust"), start=1
        ):
            write(sheet, r, col, entry[key]).alignment = wrap
    r += 2
    for col, header in enumerate(INTERNAL_CONSIDERED_COLUMNS, start=1):
        write(sheet, r, col, header).font = Font(bold=True)
    for entry in inner.get("considered", []):
        r += 1
        for col, key in enumerate(("standard", "status", "method", "reason"), start=1):
            write(sheet, r, col, entry[key]).alignment = wrap
    for col, width in zip("ABCD", (30, 22, 70, 70), strict=True):
        sheet.column_dimensions[col].width = width


#: Item 14 (owner order 3 Nov, CRS_RULES_NOTE_ENABLED): the ONE note at the top of the CRS, both copies. A draft
#: row is never labelled one by one; a row marked with a tick uses an approved rule.
RULES_NOTE = (
    "Rules used in this review are drafts built from the standards and checked by code; "
    "rows marked ✔ use an approved rule. An engineer must confirm this CRS."
)


def with_rules_note(run_status_note) -> str:
    """Row 1's note: the run status as it was, then the one rules note when the switch is on."""
    from .config import settings

    said = str(run_status_note or "")
    if not settings.crs_rules_note_enabled:
        return said
    return f"{said}\n{RULES_NOTE}" if said else RULES_NOTE
