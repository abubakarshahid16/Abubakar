"""ONE list of POINTS for a review of a paper, worst first (owner, 12 Nov 2026, the redesigned review page; SPEC.md).

A point is one thing an engineer has to look at: a comment of the rule check or a line of the AI review, in ONE vocabulary, ONE severity
order and with ONE decision state. This module only READS (nothing is written, no model, no network): the stored lines of the AI review
(`agent_review_line`), the rows of the rule check's CRS (`main._crs_content`), the decisions (`review_point_decisions`) and the points an
engineer added.

THE ORDER (`RANKS`): 1 proven Fail, 2 two-reader not met, 3 one-reader not met, 4 question, 5 one-reader met, 6 two-reader met,
7 proven Pass, 8 does not apply or not reviewed; inside a rank a "shall" rule before a "should" rule. The AI lines take their rank from
`crs_ai_workbook.status_of` (the same function that orders the AI sheet), the rule check's rows from `crs_normal.crs_status`.

THE FOUR TILES (`TILE_OF_RANK`): Not met = ranks 1 to 3, Questions = 4, Met = 5 to 7, Does not apply = 8. Every count says what it
counts; a split the review cannot have is absent (None), never 0.

NOTHING UNPROVEN IS SHOWN AS PASS OR FAIL. A point's pill says "proven by code" only for the class the code compared; "two readers" only
for the class "AI verdict, two readers agree"; everything else the AI said is "one reader". The quote boxes hold a quote ONLY when code
verified it (`quotes_checked` of the line; for the rule check, a citation that resolves to the page: a located passage, not a compared
quote); otherwise the quote is None and the plain line says so. The paper quote and the clause quote are never invented.

ACCESS (CLAUDE.md rule 5): a rule book the viewer may not read is COUNTED ("other rule books"), never named; the point still shows, with
no book name. A filter only narrows what the caller may read.

No document text is logged. No code word reaches the words a point carries (`crs_ai_words.has_banned` is applied to the names).
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

from . import agent_review_not_applicable as not_applicable
from . import agent_review_wording as wording_mod
from . import crs_ai_actions as actions
from . import crs_ai_header
from . import crs_ai_words as words
from . import review_points_content as content

#: rank -> (what it is, how firm). The pill is "what · how firm".
RANKS: dict[int, tuple[str, str]] = {
    1: ("Not met", "proven by code"),
    2: ("Not met", "two readers agree"),
    3: ("Not met", "one reader"),
    4: ("Question", ""),
    5: ("Met", "one reader"),
    6: ("Met", "two readers agree"),
    7: ("Met", "proven by code"),
    8: ("Does not apply", ""),
    9: ("AI thinks it does not apply, to confirm", ""),  # owner on PR #1872: its own section (`agent_review_not_applicable`)
}
TILES = ("not_met", "questions", "met", "does_not_apply")
TILE_OF_RANK = {
    1: "not_met",
    2: "not_met",
    3: "not_met",
    4: "questions",
    5: "met",
    6: "met",
    7: "met",
    8: "does_not_apply",
    9: "na_to_confirm",  # not one of the four tiles: counted apart (`counts`, "not_applicable_to_confirm")
}
TILE_WORDS = {
    "not_met": "Not met",
    "questions": "Questions for you",
    "met": "Met",
    "does_not_apply": "Does not apply",
}
#: `crs_ai_words.ORDER_*` of an AI item row -> rank.
_RANK_OF_AI_ORDER = {
    words.ORDER_FAIL: 1,
    words.ORDER_AI_VERDICT_NOT_MET: 2,
    words.ORDER_AI_NOT_MET: 3,
    words.ORDER_QUERY: 4,
    words.ORDER_AI_MET: 5,
    words.ORDER_AI_VERDICT_MET: 6,
    words.ORDER_PASS: 7,
}
#: The rule check's CRS Status -> rank (it never writes the two-reader class).
_RANK_OF_RC_STATUS = {
    words.STATUS_FAIL: 1,
    words.STATUS_AI: 3,
    words.STATUS_QUERY: 4,
    words.STATUS_PASS: 7,
}

SOURCE_RULE_CHECK, SOURCE_AI_REVIEW, SOURCE_ADDED = "rule_check", "ai_review", "added"
SOURCE_WORDS = {
    SOURCE_RULE_CHECK: "Rule check",
    SOURCE_AI_REVIEW: "AI review",
    SOURCE_ADDED: "Added by an engineer",
}
NO_PAPER_QUOTE = "No verified quote from the paper for this point."
NO_CLAUSE_QUOTE = "No verified quote from the rule book clause for this point."
NO_BOOK_ACCESS = "Not shown: the rule book is not one you may read, or the point is not linked to a held rule book."
PAPER_CHECK = "Checked by code: found on the page."
CLAUSE_CHECK = "Checked by code: found in the clause."
CLAUSE_CHECK_CUT = "Checked by code against the clause text read from the rule book; its pages were not searched for this quote."
CLAUSE_SCANNED = " The book is a scan: this is its recognised text."
CLAUSE_CHECK_PAGE = "Checked by code: found in the rule book on page {page}."
CLAUSE_CHECK_OTHER_PAGE = "Checked by code: found in the rule book on page {page}, not on the page the rule cites (page {stated})."
PASSAGE_PAPER_CHECK = "Checked by code: this passage is on the page."
PASSAGE_CLAUSE_CHECK = "Checked by code: this passage is in the clause."
ROUTE_INDEPENDENT = "Two readers reached this verdict independently."
ROUTE_SAW_FIRST = "A second reader checked this verdict and saw the first answer."
#: FTU-17: an AI point's engine is the engine that READ its line (`crs_ai_header.engine_of_line`), never a fixed "on Claude"
ENGINE_RC = "Rule check"


def _clause_note(line: dict) -> str:
    """What code checked about the clause quote, with the TRUE page when it found the quote in the rule book's own pages (c11); the
    clause text cut from the book says its pages were not searched; a line stored with no record of the check says the old words."""
    book = line.get("clause_book")
    if not isinstance(book, dict) or book.get("found") is not True:
        return CLAUSE_CHECK
    if book.get("where") == "the clause text cut from the book" or book.get("page") is None:
        return CLAUSE_CHECK_CUT
    stated = line.get("clause_page")
    scanned = CLAUSE_SCANNED if book.get("scanned") else ""
    if book.get("where") == "the stated page" or stated in (None, "", book["page"]):
        return CLAUSE_CHECK_PAGE.format(page=book["page"]) + scanned
    return CLAUSE_CHECK_OTHER_PAGE.format(page=book["page"], stated=stated) + scanned


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def rank_of_ai_line(line: dict) -> tuple[int, str | None, int | None]:
    """(rank, status word, row order) of one stored AI line; rank 8 for a line that is not an item row. A line of the general review's
    'rule book not held' kind is NOT a point (it is counted apart): rank 0."""
    from . import crs_ai_workbook as wb
    from .agent_review_crs import sheet_of

    got = wb.status_of(line)
    if got is not None:
        return _RANK_OF_AI_ORDER.get(got[1], 4), got[0], got[1]
    if wb.OTHER_KIND_OF_SHEET.get(sheet_of(line)) == words.KIND_NOT_HELD:
        return 0, None, None
    return 8, None, None


def group_key(
    source: str,
    rank: int,
    book: str | None,
    clause: str | None,
    reason: str | None,
    field: str | None = None,
) -> str | None:
    """THE one definition of "N alike" (owner: "Group repeated questions"): points that ask the same thing of the same field against
    the same clause of the same rule book. The key is the rule book's identity (its document id), the clause, the field (the name with
    its tag list taken off) and the reason code; the PAGE is not in it, so the same field on several pages with the same wording is
    one group. Only a question or a not-met point of the same source can group; a point with no rule book, or with neither a clause
    nor a field to compare, never groups."""
    if rank not in (3, 4) or not _clean(book) or not (_clean(clause) or _clean(field)):
        return None
    return "|".join(
        (
            source,
            str(rank),
            _clean(book).lower(),
            _clean(clause).lower(),
            _clean(field).lower(),
            _clean(reason).lower(),
        )
    )


def code_question_key(line: dict) -> str | None:
    """The reason of a question a CODE line (the calculator's) asks, with its field name and its numbers taken out, so that every check the sheet could not
    make for the SAME reason is one group ("the sheet defers a value to the contractor", "the fluid phase is not stated"). None for any other line."""
    if str(line.get("source") or "").strip().casefold() != "code":
        return None
    why = _clean(line.get("why") or (line.get("compare") or {}).get("reason")).lower()
    for part in (
        str(line.get("field") or "").lower(),
        str(line.get("equipment_tag") or "").lower(),
    ):
        if part:
            why = why.replace(part, " ")
    why = re.sub(
        r"\bpages?\s+[0-9]+(?:\s*[-,]\s*[0-9]+)*|\bp\.\s*[0-9]+", " ", why
    )  # only the page references go: the numbers that make two questions different stay
    return " ".join(why.split()) or None


# ------------------------------------------------------------------------------------------------ a name is the field, not its tags

_OPEN, _CLOSE = "([{", ")]}"
_TAG_LEAD = re.compile(r"^[A-Za-z]{1,6}[-/]\d[\w\-./]*$")  # the first token of a tag entry: letters, a dash or slash, digits ("V-100"); never letters+digits alone ("M12", "H2")
_ONE_TAG = re.compile(r"^[A-Za-z]{1,6}-\d[\w\-./]*$")
_MORE = re.compile(r"^(?:\.{2,}|\u2026|etc\.?|(?:and\s+)?\+?\d+\s+more)$", re.I)
_SEPARATORS = ",;&+"


def _top_level_groups(text: str) -> list[tuple[int, int]]:
    """(start, end) of every outermost bracketed group (balanced, so a group inside a group stays inside it)."""
    out, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch in _OPEN:
            if depth == 0:
                start = i
            depth += 1
        elif ch in _CLOSE and depth > 0:
            depth -= 1
            if depth == 0:
                out.append((start, i + 1))
    return out


def _entries(inner: str) -> list[str]:
    """The entries of a group: its text cut at "," ";" "&" "+" and the word "and" outside any inner bracket."""
    parts, depth, cur, words = [], 0, [], inner.replace(" and ", " & ")
    for ch in words:
        depth += (ch in _OPEN) - (ch in _CLOSE)
        if depth == 0 and ch in _SEPARATORS:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [x.strip() for x in parts if x.strip()]


def _fold_tag(text: str) -> str:
    return "".join(str(text or "").upper().split())


_TAG_SUFFIX = re.compile(r"^(?:[A-Z0-9]{1,2}|[A-Z0-9]{1,3}/[A-Z0-9]{1,3})$")  # "A", "10", "A/B": a range or suffix of a tag, never a word


def _tag_shaped(entry: str) -> bool:
    """The FALLBACK test of one entry: its lead token has the dash/slash tag shape, and whatever follows the lead (outside a bracketed note)
    is only a range ("A/B") or another tag, never words: "V-1 A/B (inlet)" is a tag, "V-1 shall be painted" is a sentence."""
    lead, _, rest = re.sub(r"\([^()]*\)", " ", entry).strip().partition(" ")
    if not _TAG_LEAD.match(lead.rstrip(",;")):
        return False
    return all(_TAG_SUFFIX.match(t) or _TAG_LEAD.match(t) for t in rest.split())


def _is_known(entry: str, known: frozenset[str]) -> bool:
    """An entry IS a known tag: its lead token equals one (folded), or is a suffix form of one ("V-1A" for "V-1"), or stands inside a
    known tag value that lists several tags; and whatever follows the lead token is a range/suffix ("A/B") or a bracketed note, never a
    word. So "V-1 A/B (inlet)" is a tag of a known "V-1", and "M12 bolts" is NOT a tag of a known "M12" (it merely contains one)."""
    lead, _, rest = re.sub(r"\([^()]*\)", " ", entry.split("(")[0]).strip().partition(" ")
    folded = _fold_tag(lead)
    if len(folded) < 3 or not all(_TAG_SUFFIX.match(t) for t in rest.split()):
        return False
    return any(folded == k or folded in k or (folded.startswith(k) and len(folded) - len(k) <= 2) for k in known)


def _is_tag_list(inner: str, known: frozenset[str] = frozenset()) -> list[str] | None:
    """The entries of a bracketed group when every entry IS a tag. PREFERRED: the review knows this paper's tags (`known`, folded):
    each entry must be one of them, whole or as a part of one (a range or suffix: "V-1 A/B" for "V-1"; a tag value that lists several tags). FALLBACK, when the paper has no known tag:
    each entry's lead token has the dash/slash tag shape ("V-100"; never letters and digits alone: "M12", "H2"). A unit, a standard's
    number, a quantity or a note ("(barg)", "(API 610)", "(H2 and CO2 content)", "(M12 bolts, M16 nuts)") is NOT a tag list. When in doubt
    the bracket STAYS in the name: a tag left in a name is ugly, a name word removed is wrong."""
    items = [x for x in _entries(inner) if not _MORE.match(x)]
    if not items:
        return None
    if known:
        ok = all(_is_known(x, known) for x in items)
    else:
        ok = all(_tag_shaped(x) for x in items)
        ok = ok and (len(items) > 1 or bool(_ONE_TAG.match(items[0].split()[0])))
    return items if ok else None


def split_tags(name: str, known: frozenset[str] = frozenset()) -> tuple[str, list[str]]:
    """(the name with every bracketed list of equipment tags taken off, the tags in the order they stood). The tags belong in the
    opened point ("Applies to: N tags"), never in the collapsed row's name. Nested brackets ("V-1 A/B (inlet, 10 & 19) & V-2") and
    every separator the sheet uses are handled; a group that is not a tag list stays in the name."""
    text = str(name or "")
    tags: list[str] = []
    keep, last = [], 0
    for start, end in _top_level_groups(text):
        got = _is_tag_list(text[start + 1 : end - 1], known)
        if got is None:
            continue
        tags.extend(got)
        keep.append(text[last:start].rstrip())
        last = end
    keep.append(text[last:])
    return _clean(" ".join(x for x in keep if x)), list(dict.fromkeys(tags))


def _pill(rank: int, other_kind: str | None, n_alike: int, added_by: str | None) -> str:
    if added_by:
        return "Added by " + added_by
    what, firm = RANKS[rank]
    if rank == 8 and other_kind:
        what = other_kind
    if rank == 4 and n_alike > 1:
        return f"{what} · {n_alike} alike"
    return f"{what} · {firm}" if firm else what


def _plain(text) -> str:
    """A name or a sentence with any code word removed (the AI sheet's own rule); '' when nothing plain is left."""
    text = _clean(text)
    return "" if not text or words.has_banned(text) else text


def rule_book_hidden(book_doc, ctx: dict, proof: tuple[bool, bool] | None = None) -> bool:
    """THE one readability test of a point's rule content (CLAUDE.md rule 5: classification is not access; a filter only narrows). Both the
    AI point and the rule-check point use it. A rule-check point passes the PROOF the service computed once (`review_points_service`):
    its requirement-derived content is shown only when readability is PROVEN for this viewer (a linked book he may read; a stored reference
    that resolves to held books he may all read; the app's own approved checklist as the proven origin; or a viewer who may read the whole
    library); anything else is hidden. An AI point passes no proof: its book is hidden when it is held and the viewer may not read it.
    A hidden point carries no requirement text, no clause text, no book name and nothing derived from the requirement (it is counted,
    never named)."""
    if proof is not None:
        return not proof[0]
    return bool(book_doc) and book_doc not in ctx["readable"]


def ai_free_text_ok(line: dict, book_doc, ctx: dict) -> bool:
    """May the AI point's FREE text (its reasoning) reach this viewer? Fail closed. A whole-library viewer: yes. A linked book: only when he may
    read it. No linked book: the point's cited reference must resolve to held books he may ALL read; a point that cites no rule at all is
    shown only when its free text names no held book he may not read (the same matcher, `standard_ids`, against the held books' names)."""
    if "library" not in ctx:
        return not rule_book_hidden(book_doc, ctx)
    if ctx.get("everything"):
        return True
    if book_doc:
        return book_doc in ctx["readable"]
    from . import applicability, standard_ids

    cited = " ".join(str(line.get("standard") or "").split())
    library, readable = ctx["library"], ctx["readable"]

    def hits(text: str) -> list[str]:
        out = []
        for name in standard_ids.cited_standards(text) or ([text] if text else []):
            out += [e["id"] for e in library if any(standard_ids.same_standard(name, n) for n in applicability._library_names(e))]
        return out

    if cited:  # it cites a rule: the reference must resolve, and only to books the viewer may read
        found = hits(cited)
        return bool(found) and all(h in readable for h in found)
    text = " ".join(str(line.get("reasoning") or "").split())
    # cites none: no held book he may not read may be NAMED in the words (`standard_ids.names_standard`, the matcher that finds a standard in text)
    return not any(
        standard_ids.names_standard(text, n)
        for e in library
        if e["id"] not in readable
        for n in applicability._library_names(e)
    )


def ai_point(line: dict, ctx: dict) -> dict | None:
    """One AI line as a point; None for a line that is not a point (a rule book not held). `ctx`: run_id, paper_document_id,
    book_of (item id -> (document id, name)), readable (frozenset of document ids the caller may read)."""
    from . import agent_general_crs as general
    from . import agent_review_crs as arc
    from . import crs_ai_workbook as wb
    from .agent_review_two_reader import is_independent

    rank, status, order = rank_of_ai_line(line)
    if rank == 0:
        return None
    if rank == 4 and wording_mod.not_applicable_question(line):
        rank = 9  # owner on PR #1872: an unproven "does not apply" is its own section, never a main question
    item = str(line.get("item_id") or "")
    book_doc, _name = ctx["book_of"].get(item, (None, None))
    if not book_doc and line.get("standard_document_id") in ctx.get("documents", ()):
        # order 14 lane B: a checklist line has no asked-rule row; its book is the held document the line itself stored
        book_doc = line["standard_document_id"]
    book_name = (
        _plain(line.get("standard"))
        if book_doc and not rule_book_hidden(book_doc, ctx)
        else None
    )
    clause = _clean(line.get("clause")) or None
    quotes = line.get("quotes_checked") or {}
    paper_q = (
        _clean(line.get("paper_quote"))
        if quotes.get("paper") and _clean(line.get("paper_quote"))
        else None
    )
    # FTU-1: a line whose own reason says the paper does not state the value: its found quote is never shown as evidence; it is
    # where it looked, or (when it may state the value) the engineer's to check
    silent = actions.silent_row(line) if paper_q else None
    # a code-proved absence: its proof, never the reader's quote, is the paper side
    proof = actions.absence_proof(line)
    shown_as = (paper_q, None) if paper_q and (silent or proof) else (None, paper_q)
    looked, paper_q = shown_as
    proved = f"{proof[:1].upper()}{proof[1:]}." if proof else NO_PAPER_QUOTE
    book_readable = bool(book_name)
    # The rule book's own words are the book's: a caller who may not read the book gets neither its name nor its text (rule 5).
    clause_q = (
        _clean(line.get("clause_quote"))
        if book_readable and quotes.get("clause") and _clean(line.get("clause_quote"))
        else None
    )
    other_kind = None
    if rank == 8:
        from .agent_review_crs import sheet_of

        other_kind = wb.OTHER_KIND_OF_SHEET.get(sheet_of(line))
    two_readers = rank in (2, 6)
    page = arc.line_page(line)
    field, tags = split_tags(wb.field_words(line), ctx.get("known_tags") or frozenset())
    name = (
        _plain(field)
        or (_plain(arc.against(line)) if book_name else "")
        or "A point of the AI review"
    )
    # The reason is part of the group key: points asked for different reasons (value blank, values conflict, held for a condition)
    # are never one group, so "Keep all" never decides them unseen.
    reason = line.get("reason_code") or line.get("not_proven_reason") or ""
    shown = (
        line
        if book_readable
        else {
            **line,
            "standard": "",
            "clause": "",
            "clause_quote": "",
            "requirement": "",
        }
    )
    if general.is_general(line):  # LP2: every cell from the line's one home
        # its free words and names reach a viewer only when they name no book he may not read
        free = ai_free_text_ok({"reasoning": general.free_words(line)}, None, ctx)
        shown = {**shown, general.HIDE_KEY: not free}
        paper_q = general.question_row(shown).paper_quote or None
    action = (
        ""
        if rank == 8
        else _plain(
            wb._contractor_to(shown, status or "", order if order is not None else 3)
        )
    )
    return {
        "id": f"ai:{ctx['run_id']}:{item}",
        "source": SOURCE_AI_REVIEW,
        "source_words": SOURCE_WORDS[SOURCE_AI_REVIEW],
        "engine": crs_ai_header.engine_words(
            crs_ai_header.engine_of_line(line, ctx.get("run_engine", ""))
        ),
        "rank": rank,
        "tile": TILE_OF_RANK[rank],
        "firm": RANKS[rank][1] or None,
        "other_kind": other_kind,
        "name": name,
        "page": page,
        "page_note": arc.page_note(line),  # a page hint is printed as one (`crs_comments.point_page_words`), never as THE page
        "rule_book": book_name,
        "clause": clause if book_name else None,
        "action": action or None,
        # U5d: the line's STORED words when code did not verify them (shown as stored, "not verified by code"); never when the book is unreadable
        "paper_value": (
            None if paper_q or looked else (_clean(line.get("paper_quote")) or None)
        ),
        "paper_value_page": page,
        "rule_text": (None if clause_q or not book_readable else shown_rule_words(book_doc, line.get("clause_quote") or line.get("requirement"),
                                                                                 line.get("rule_page") or line.get("clause_page"), ctx)),
        "_rule_stored": (None if clause_q or not book_readable else (_clean(line.get("clause_quote") or line.get("requirement")) or None)),
        "checked_by": content.AI_REVIEW_BY,
        "paper_quote": paper_q,
        "paper_looked": looked,
        # the paper side is code's own proof (its note), with or without a reader's quote
        "paper_proof": bool(proof),
        "clause_quote": clause_q,
        "paper_quote_note": PAPER_CHECK
        if paper_q
        else (silent.note if silent else proved),
        "clause_quote_note": _clause_note(line)
        if clause_q
        else (NO_CLAUSE_QUOTE if book_readable else NO_BOOK_ACCESS),
        "route_note": (ROUTE_INDEPENDENT if is_independent(line) else ROUTE_SAW_FIRST)
        if two_readers
        else None,
        "view_page": _view_page(ctx.get("paper_document_id"), page),
        "shall": not bool(line.get("recommendation")),
        # P6: the priority comes from the finding (`crs_ai_words.priority_ai`); P5: the AI's own reasoning, labelled, never for a proven line
        "priority": words.priority_ai(status, line, order) if status else "",
        "ai_reasoning": actions.reasoning_part(line, status or "", "").strip() if ai_free_text_ok(line, book_doc, ctx) else "",  # free words that can name a book the viewer may not read: the field is removed
        "group_key": group_key(
            SOURCE_AI_REVIEW,
            rank,
            book_doc if book_name else None,
            clause,
            str(reason),
            _plain(field),
        )
        if not ((code_why := code_question_key(line)) and rank == 4)
        else group_key(
            SOURCE_AI_REVIEW, rank, "approved checklist", "any check", code_why
        ),
        "tags": tags,
        "added_by": None,
        "_book_doc": book_doc,
        "_book_docs": [book_doc] if book_doc else [],
        "_line": shown,  # the stored line (the rule book's words already left out for a caller who may not read the book): the one-CRS export reads it
    }


def _view_page(document_id: str | None, page) -> dict | None:
    """The existing page-image route of the document at that page: the target of "View page". None without a page."""
    if (
        not document_id
        or not isinstance(page, int)
        or isinstance(page, bool)
        or page < 1
    ):
        return None
    return {
        "document_id": document_id,
        "page": page,
        "image_url": f"/api/documents/{document_id}/pages/{page}/image",
    }


_PAGE = re.compile(r"\b(?:page|p\.?)\s*(\d{1,4})", re.I)


def shown_rule_words(book_doc, text, page, ctx: dict) -> str | None:
    """A point's stored rule words as the page and the CRS show them as the BOOK's words: only where code finds them in the linked
    held book (`agent_review_standards.book_words`: whole, or in pieces with a visible mark where the book has other text between
    them); None otherwise (no linked book, or words the book does not hold). Each book is read once per listing (`ctx`)."""
    from . import agent_review_standards as standards

    if not book_doc or not _clean(text):
        return None
    return standards.book_words(book_doc, text, page, ctx.setdefault("_book_pages", standards.BookPages()))


def clause_unconfirmed(book_doc, clause, finding: dict | None, ctx: dict) -> str:
    """The rule check's cited clause when code is CERTAIN it does NOT hold the rule's stored words in the linked book (the same test as
    the AI lines, `crs_ai_words.mark_clause_unconfirmed`: `agent_review_standards.clause_holds` False), else "". A doubt
    (`CLAUSE_UNSURE`) or "cannot tell" keeps the clause: a rule check point has no place to say "not checked". Each book's text is
    read once per listing (`ctx`)."""
    from . import agent_review_standards as standards

    if not book_doc or not _clean(clause) or not finding:
        return ""
    got = standards.clause_holds(book_doc, _clean(clause), content.rule_text(finding), finding.get("standard_page"),
                                 ctx.setdefault("_book_texts", {}))  # fmt: skip
    return _clean(clause) if got is False else ""


def rule_point(
    row: dict,
    ctx: dict,
    finding: dict | None,
    sides: dict,
    *,
    strength: str = "unknown",
    proof: tuple[bool, bool] | None = None,
    app_text_only: bool = False,
) -> dict:
    """One CRS row of the rule check as a point. `finding`: its stored finding (or None); `sides`: {"submittal": .., "standard": ..}
    as `evidence_boxes.side` answered (document None when the side cannot be shown)."""
    from . import crs_normal
    from .crs_mapping import (
        ROW_KIND_ENGINEER_COMMENT,
        ROW_KIND_PAGE_READER_ONLY,
        ROW_KIND_PAGES_NOT_READABLE,
    )

    kind = row.get("row_kind")
    status = crs_normal.crs_status(kind, row.get("priority"))
    rank = _RANK_OF_RC_STATUS.get(status, 4)
    other_kind = None
    if kind in (ROW_KIND_PAGES_NOT_READABLE, ROW_KIND_PAGE_READER_ONLY):
        rank, other_kind = 8, words.KIND_NOT_REVIEWED
    added_by = None
    if kind == ROW_KIND_ENGINEER_COMMENT:
        rank = 4
        added_by = (
            _plain(
                str(row.get("comment_by") or "").replace("Engineer", "").strip(" :-")
            )
            or "an engineer"
        )
    key = str(row.get("finding_id") or row.get("crs_row_key") or "")
    comment = _clean(row.get("comment"))
    section = _clean(row.get("page_section"))
    m = _PAGE.search(section)
    side_p, side_s = sides.get("submittal") or {}, sides.get("standard") or {}
    page = side_p.get("page") or (
        int(m.group(1)) if m else None
    )  # the cited page, only of a document the caller may read
    book_doc = (finding or {}).get("standard_document_id")
    hidden = rule_book_hidden(book_doc, ctx, proof if proof is not None else (not (book_doc and book_doc not in ctx["readable"]), True))
    ref_hidden = hidden or (proof is not None and not proof[1])  # the stored reference names a book: only when that is proven readable too
    book_name = (
        _plain(row.get("standard_reference"))
        if book_doc and not hidden
        else None
    )
    paper_q = (
        _clean((finding or {}).get("contractor_evidence_text"))
        if side_p.get("verified") and finding
        else ""
    )
    # FTU-1: a point whose own record says the paper gives no value shows the found passage only as where it looked, never as evidence
    looked, paper_q = (
        (paper_q, "")
        if paper_q and content.says_no_value(kind, finding)
        else ("", paper_q)
    )
    clause_q = (
        _clean((finding or {}).get("requirement_source_text"))
        if side_s.get("verified") and finding
        else ""
    )
    reason = (finding or {}).get("reason_code") or kind or ""
    field, tags = split_tags(
        content.field_of(section.split(" - ", 1)[-1] if " - " in section else "", row, finding, allow_rule=not ref_hidden),
        ctx.get("known_tags") or frozenset(),
    )
    name = (
        _plain(field)
        # FTU-1: a shortened name carries its mark (the whole comment is the point's action)
        or _plain(content._head(comment, 7))
        or "A point of the rule check"
    )
    if page is None and finding:  # the finding's own page of the paper (only a finding the caller may read reaches here)
        page = content.paper_value(finding)[1]
    value, value_page = content.paper_value(finding)
    # a hidden book's point: the check's own comment only (no fallback to the finding's or the AI's words, which can quote the requirement)
    if finding and finding.get("requirement_id"):  # lane C's re-read: never the old clause of a superseded requirement
        shown = dict(finding)
        reread_clauses([shown], ctx.setdefault("_reread", {}))
        if shown.get("clause_reread"):
            finding = {**finding, "standard_clause": shown.get("paragraph_id") or ""}
    action, action_source = content.action_of(row, finding, _plain, own_only=hidden, comment_only=app_text_only)
    ref = content.rule_ref(row, finding)
    # a viewer for whom the reference is hidden (rule 5) gets the hidden point unchanged: a book name is never shown to him
    missing = book_missing(book_doc, ref["name"], ctx) if kind != ROW_KIND_ENGINEER_COMMENT and not ref_hidden else ""
    unconfirmed = "" if missing or ref_hidden else clause_unconfirmed(book_doc, ref["clause"], finding, ctx)
    if unconfirmed:  # the clause does not hold the rule's words in the book: no clause is cited (the grouping keeps it)
        ref = {**ref, "clause": ""}
    unproven_ai = False
    missing_words = book_missing_words(missing, ref["clause"]) if missing else ""  # order 14 lane C (C1): the clause, or "not named"
    if missing:  # order 14 lane B (lane D, G7): a rule whose book is not held is a question, never a verdict; none of its words shown
        rank, other_kind = 4, None
        rule_words = ref["clause"] or content.rule_text(finding)
        if rule_words or action_source != "check":  # a check's own sentence that cites no rule of the book (a missing reference) stays
            action, action_source = f"{missing_words}. {BOOK_NOT_CHECKABLE}; engineer to check.", "check"
        ref = {"name": ref["name"], "clause": "", "page": None}
    elif rank == 3 and kind in _AI_WRITTEN_RULE_KINDS and not _clean((finding or {}).get("standard_clause")):
        # Honesty rule 4 (no claim without a resolving citation; gates G1 and G5): a "not met" written by the rule check's AI step whose
        # finding names no clause is a question for the engineer, never a verdict (decided on the stored finding: the same for every viewer).
        # Order 14, 16 Nov 2026: the same check named a book NOT held in one run (a question) and the held book's file in the next
        # (a "not met" with no clause), so the sheet changed from run to run on wording alone.
        rank, unproven_ai = 4, True
    # FTU-1: a point whose own record says no value, with a found passage: ALL its wording cells from the one silent-row decision
    f = finding or {}  # FTU-16: a field that asks for a value reads "By Contractor" as a value left to be given
    value_field = bool((f.get("_fact") or {}).get("unit")) or actions.asks_a_value(content.rule_text(finding), f.get("requirement_source_text"))
    silent = actions.silent_row_words(_plain(field), looked, [field], value_field=value_field) if looked else None
    if silent and not missing and action_source != "hidden":
        action, action_source = silent.action, "check"
    point = {
        "id": f"rc:{key}",
        "source": SOURCE_RULE_CHECK,
        "source_words": SOURCE_WORDS[SOURCE_RULE_CHECK],
        "engine": ENGINE_RC,
        "rank": rank,
        "tile": TILE_OF_RANK[rank],
        "firm": RANKS[rank][1] or None,
        "other_kind": other_kind,
        "name": name,
        "page": page,
        "rule_book": book_name,
        "clause": (ref["clause"] or None) if not ref_hidden else None,
        "action": action or None,
        "action_source": action_source,
        # U5d: what the stored finding itself holds, never presented as verified unless code verified it
        # FTU-1: never beside a found passage
        "paper_value": None if looked else (value or None),
        "paper_value_page": value_page,
        # order 14 lane B: our checklist's own wording is never shown as the rule book's words: it is `check_text`, labelled as ours
        # honesty rule 4 (G1): the stored words are shown as the book's only where code finds them in the linked book (`book_words`)
        "rule_text": None if hidden or is_check_text(finding) else shown_rule_words(book_doc, content.rule_text(finding), (finding or {}).get("standard_page"), ctx),
        "check_text": (content.rule_text(finding) or None) if not hidden and is_check_text(finding) else None,
        # the stored rule words as they were before the G1 rule: the comment grouping keys on them (`crs_comments._requirement_of`)
        "_rule_stored": None if hidden or is_check_text(finding) else (content.rule_text(finding) or None),
        "rule_hidden": hidden,
        "rule_ref": ref if (ref["name"] or ref["clause"]) and not ref_hidden else None,
        "reason_words": silent.reason
        if silent
        else content.reason_words(kind, finding),
        "checked_by": content.checked_by(kind),
        "paper_quote": paper_q or None,
        "paper_looked": looked or None,
        "clause_quote": clause_q or None,
        "paper_quote_note": PASSAGE_PAPER_CHECK
        if paper_q
        else (silent.note if silent else NO_PAPER_QUOTE),
        "clause_quote_note": PASSAGE_CLAUSE_CHECK if clause_q else (NO_BOOK_ACCESS if hidden else NO_CLAUSE_QUOTE),
        "route_note": None,
        "view_page": _view_page(ctx.get("paper_document_id"), page),
        "shall": strength != "should",
        "strength_unknown": strength == "unknown",
        "priority": words.priority(status, {}, words.ORDER_AI_NOT_MET),  # the rule check's own vocabulary (`crs_normal.decorate`)
        "ai_reasoning": "",
        "group_key": group_key(
            SOURCE_RULE_CHECK,
            rank,
            book_doc if book_name else None,
            None,
            str(reason),
            _plain(field),
        ),
        "tags": tags,
        "added_by": added_by,
        "finding_ids": list(
            row.get("finding_ids")
            or ([row["finding_id"]] if row.get("finding_id") else [])
        ),
        "_book_doc": book_doc,
        "_book_docs": [book_doc] if book_doc else [],
        "_book_missing": missing or None,
        "_book_missing_words": missing_words or None,
        "_clause_unconfirmed": unconfirmed or None,
        "_row_key": key,
        "_row": row,  # the CRS row and its finding: the one-CRS export reads them (private: never in the listing)
        "_finding": finding,
    }
    if missing:
        point.update(clause=None, rule_text=None, check_text=None, clause_quote=None, rule_ref=None, firm=None, reason_words=missing_words,
                     clause_quote_note=NO_CLAUSE_QUOTE, _rule_stored=None)  # fmt: skip
    if unproven_ai:  # its "rule" words were written by the AI check, not found in the book: never shown as the book's words (G1)
        point.update(rule_text=None, clause_quote=None, clause_quote_note=NO_CLAUSE_QUOTE, _rule_stored=None)
    return point


#: The rule-check kinds whose stored "requirement" is the AI check's own wording, not text the library read from the book (a clause
#: review's stored requirement IS the book's text: it stays, labelled "not verified by code").
_AI_WRITTEN_RULE_KINDS = frozenset({"ai_engineering_check", "web_standard_check"})

REREAD = "clause re-read"


def _successor_clauses(conn, book: str, cache: dict) -> tuple[dict, dict]:
    """A book's CURRENT rules by text, as lane C's label carry links them: {(requirement text, source text): {clause}} and the same with
    the rule's own heading line (its chunk's section) put in front. Read once per book (`cache`)."""
    if book not in cache:
        same: dict = {}
        headed: dict = {}
        for r in conn.execute(
            "SELECT r.clause, r.requirement_text, r.source_text, c.section FROM standard_requirements r"
            " LEFT JOIN chunks c ON c.id = r.chunk_id WHERE r.standard_document_id = ? AND r.superseded_at IS NULL",
            (book,),
        ):
            if not _clean(r["clause"]):
                continue
            req, src, sec = _clean(r["requirement_text"]), _clean(r["source_text"]), _clean(r["section"])
            same.setdefault((req, src), set()).add(_clean(r["clause"]))
            if sec:
                headed.setdefault((_clean(f"{sec} {req}"), _clean(f"{sec} {src}")), set()).add(_clean(r["clause"]))
        cache[book] = (same, headed)
    return cache[book]


def reread_clauses(findings: list[dict], cache: dict | None = None) -> None:
    """Order 14 lane B (lane C's re-read of a book): a finding whose requirement was SUPERSEDED never shows its old clause, which may be a
    false label ("2.5", "7.16"). Its reference shows the successor's clause, the current rule of the same book with identical text (or
    identical once its heading line is put back: lane C's carry), as "<clause> (clause re-read)"; with no single successor, no clause.
    In place, display only (`clause_identified` False, `paragraph_id`): the finding's own `standard_clause`, which decisions are keyed
    by, is untouched. Reads only."""
    from .db import connect

    ids = sorted({f["requirement_id"] for f in findings if f.get("requirement_id")})
    if not ids:
        return
    conn, cache, old = connect(), cache if cache is not None else {}, {}
    for start in range(0, len(ids), 500):
        part = ids[start : start + 500]
        for r in conn.execute(
            f"SELECT id, standard_document_id, requirement_text, source_text FROM standard_requirements"
            f" WHERE superseded_at IS NOT NULL AND id IN ({','.join('?' for _ in part)})",
            part,
        ):
            old[r["id"]] = r
    for f in findings:
        r = old.get(f.get("requirement_id"))
        if r is None:
            continue
        same, headed = _successor_clauses(conn, r["standard_document_id"], cache)
        key = (_clean(r["requirement_text"]), _clean(r["source_text"]))
        clauses = same.get(key) or headed.get(key) or set()
        f["clause_identified"], f["clause_reread"] = False, True
        f["paragraph_id"] = f"{next(iter(clauses))} ({REREAD})" if len(clauses) == 1 else None


BOOK_MISSING = "Book missing"
#: The sentence a book-missing point's action says after its book (the answer-key scorer reads it from here: never a find).
BOOK_NOT_CHECKABLE = "The rule cannot be checked until the book is held"
#: What a book-missing point says when the stored reference names no clause (order 14 lane C, C1): never a silent blank.
CLAUSE_NOT_NAMED = "clause not named by the reviewer"
_EDITION_YEAR = re.compile(r"(?:19|20)\d\d")
#: An edition, revision or issue number is not a clause: "11th edition", "7th", "rev 3", "Rev. B2", "edition 5", "issue 2".
_EDITION_NUMBER = re.compile(
    r"\b\d+(?:st|nd|rd|th)\b(?:\s+(?:edition|ed\.?|revision|rev\.?))?|\b(?:rev(?:ision)?|edition|ed|issue|version|ver)\.?\s*[A-Z]?\d+[a-z]?\b",
    re.I,
)


def names_a_clause(reference: str) -> bool:
    """Does a stored rule reference name a clause beyond its book(s)? Each book of the reference (";"-separated) is read on its own:
    the standard identifier `standard_ids.find_citations` reads is taken out (a book it cannot read: its first word with a digit, the
    book's own number); a number left over is a clause ("X-1 6.1", "X-1 (edition not recorded) cl. 5.2"); an edition year, an edition
    or a revision number is not ("X-1 2017", "X-1 11th edition", "X-1 rev 3")."""
    from .standard_ids import find_citations

    for part in str(reference or "").split(";"):
        part = _EDITION_NUMBER.sub(" ", part)
        spans = find_citations(part)
        rest = part
        for _raw, start, end in sorted(spans, key=lambda s: -s[1]):
            rest = rest[:start] + " " + rest[end:]
        tokens = [t.strip(".:") for t in re.split(r"[\s,()]+", rest) if re.search(r"\d", t)]
        if not spans:
            tokens = tokens[1:]  # no identifier read: the first token with a digit is the book's own number
        if any(not _EDITION_YEAR.fullmatch(t) for t in tokens):
            return True
    return False


def book_missing_words(name: str, clause: str | None) -> str:
    """THE words of a point whose rule book is not held (its action and its reason): the book and the clause the reviewer named, or
    plainly that it named none. "Book missing: X-1, clause 8.5"; "Book missing: X-1 6.1" (the reference holds the clause);
    "Book missing: X-1 (clause not named by the reviewer)"."""
    name, clause = _clean(name), _clean(clause)
    if clause:
        return f"{BOOK_MISSING}: {name}, clause {clause}"
    if names_a_clause(name):
        return f"{BOOK_MISSING}: {name}"
    return f"{BOOK_MISSING}: {name} ({CLAUSE_NOT_NAMED})"
_CHECK_TEXT = re.compile(r"^Datasheet check [A-Za-z0-9-]+:")


def is_check_text(finding: dict | None) -> bool:
    """The finding's stored rule text is our datasheet checklist's own wording ("Datasheet check <id>: ..."), not the book's."""
    f = finding or {}
    return f.get("origin") == "datasheet_check" or bool(_CHECK_TEXT.match(content.rule_text(finding)))


def book_missing(book_doc, name: str, ctx: dict) -> str:
    """The cited book's name when the library holds no document for it (no linked document and `applicability.find_standard` finds
    none), else "". The library is read once per listing (kept in `ctx`)."""
    name = _clean(name)
    if book_doc or not name:
        return ""
    from .applicability import find_standard
    from .db import connect

    if "_library" not in ctx:
        ctx["_library"] = library_of(connect())
    return "" if find_standard(ctx["_library"], name) else name


#: Priority words, worst first (a point with none sorts after the ones that have one).
PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def order_points(points: list[dict]) -> list[dict]:
    """Worst first: by rank (proven Fail, two-reader not met, AI not met, question, met), then by priority (High first), then a 'shall' rule
    before a 'should' rule, then the order they came in (stable)."""
    return [
        p
        for _i, p in sorted(
            enumerate(points),
            key=lambda ip: (
                ip[1]["rank"],
                PRIORITY_ORDER.get(ip[1].get("priority") or "", 3),
                0 if ip[1].get("shall", True) else 1,
                ip[0],
            ),
        )
    ]


def with_groups(points: list[dict]) -> list[dict]:
    """Fill `n_alike` (the size of the group, 1 for a point that stands alone) and the pill words, in place; returns the points."""
    size = Counter(p["group_key"] for p in points if p.get("group_key"))
    for p in points:
        n = size.get(p.get("group_key"), 1) if p.get("group_key") else 1
        p["n_alike"] = n
        p["pill"] = _pill(p["rank"], p.get("other_kind"), n, p.get("added_by"))
    return points


#: A clause number, with its clause / section / paragraph word when one is printed ("Sec. 5.3", "Sec.5.3": the dot needs no space).
_CLAUSE_TOKEN = re.compile(
    r"(?:\b(?:cl(?:ause)?|section|sec|para(?:graph)?)(?:\.\s*|\s+)|(?<![\w.]))(\d+(?:\.\d+)*[A-Za-z]?|[A-Z]{1,3}-\d+(?:\.\d+)*[A-Za-z]?)(?![\w.])",
    re.I,
)
#: A number after one of these words is part of the BOOK's name, never its clause ("Section 6.1" IS a clause) ("Part 2", "Table 5", "Class 300", "type 3.1").
_BOOK_QUALIFIER = re.compile(
    r"\b(?:part|pt|table|tab|annex|appendix|class|type|ed|edition|rev|revision|issue|div|division|vol|volume)\.?\s*$", re.I
)


def book_and_clause(reference: str) -> tuple[str, str | None]:
    """FTU-16: (the book, the clause or None) of one stored rule reference: "IEC 61882 6.1" is the book "IEC 61882" and the clause "6.1".
    The clause exists only when `names_a_clause` says the reference names one beyond its book; the book ends where the identifier
    `standard_ids.find_citations` reads ends (a book it cannot read: at its first token with a digit, the book's own number). An edition
    year is never the clause, and a number after Part / Pt / Table / Annex / Class / Type / Div / edition words stays in the book's
    name ("X-1 Part 2" and "X-1 Part 3" are two books). General: identifiers and numbers only, no book's own spelling."""
    from .standard_ids import find_citations

    text = _clean(reference)
    if not text or ";" in text or not names_a_clause(text):
        return text, None
    spans = find_citations(text)
    if spans:
        end = min(spans, key=lambda sp: sp[1])[2]
    else:
        first = re.search(r"\S*\d\S*", text)
        end = first.end() if first else len(text)
    rest = _EDITION_NUMBER.sub(lambda m: " " * len(m.group(0)), text[end:])
    for m in _CLAUSE_TOKEN.finditer(rest):
        if _EDITION_YEAR.fullmatch(m.group(1)) or _BOOK_QUALIFIER.search(rest[: m.start()]):
            continue  # an edition year, or a part / table / class ... number: the book's own name
        book = (text[:end] + text[end:][: m.start()]).strip(" ,;:-(")
        return (book or text), m.group(1)
    return text, None


def book_name_of(reference: str) -> str:
    """The book alone of a stored reference (`book_and_clause`): what the list of rule books not held names and counts."""
    return book_and_clause(reference)[0]


def _books_marked(point: dict) -> list[str]:
    """The books ONE point marks as not held: a rule-check row's "Book missing" (its reference may join several books with ";") and
    an AI review's note "Rule book not held" (`review_points_notes.missing_book_points`), each book without its clause."""
    names = [*str(point.get("_book_missing") or "").split(";"), point.get("_not_held_book") or ""]
    return [n for n in (book_name_of(x) for x in names) if n]


def books_not_held(run_books: list[str], points: list[dict], library: list[dict]) -> list[str]:
    """THE rule books not held of a paper's list, each once: the AI run's own record first, each name tested again against today's
    `library` (a book uploaded after the run leaves the list), then every book a point marks "Book missing" (`_book_missing`, the name
    its row prints, decided at read time by `book_missing`), in list order. The page's "not held" count and the CRS sheet "Rule books
    not held" both read it, so the sheet never says 0 while rows say "Book missing" (order 14, first-time-user test 15). Same book:
    `standard_ids.same_standard`, the notion `applicability.find_standard` uses ("API RP 520 Pt-1" is "API 520 Part I"). FTU-16: each
    name is the book alone (`book_name_of`: "IEC 61882 6.1" is "IEC 61882"), so a book is listed and counted once, never with a clause."""
    from .applicability import find_standard
    from .standard_ids import same_standard

    out: list[str] = []
    names = [n for n in (run_books or []) if not find_standard(library, str(n or ""))]
    for name in [*names, *(b for p in points for b in _books_marked(p))]:
        name = book_name_of(" ".join(str(name or "").split()))
        if name and not any(same_standard(name, seen) for seen in out):
            out.append(name)
    return out


def not_held_rows(not_held: list[str], points: list[dict]) -> dict[str, int]:
    """FTU-16: {book of `not_held`: how many points (rows) mark it not held}; 0 for a book only the review's scope found not held, that
    no row cites. The two sources are kept apart on the sheet and in the page's count: they are different statements."""
    from .standard_ids import same_standard

    rows = dict.fromkeys(not_held, 0)
    for p in points:
        for hit in _held_hits(not_held, p, same_standard):
            rows[hit] += 1
    return rows


def _held_hits(not_held: list[str], point: dict, same) -> list[str]:
    """The books of `not_held` that ONE point marks, each once."""
    hits = (next((b for b in not_held if same(name, b)), None) for name in _books_marked(point))
    return list(dict.fromkeys(h for h in hits if h is not None))


def points_marking(not_held: list[str], points: list[dict]) -> int:
    """How many points mark at least one book of `not_held` (a point that marks two books counts once)."""
    from .standard_ids import same_standard

    return sum(1 for p in points if _held_hits(not_held, p, same_standard))


def counts(
    points: list[dict],
    *,
    two_reader_possible: bool,
    not_held: list[str],
    decided: int | None = None,
) -> dict:
    """The four tiles with their splits, the groups, the per-rule-book counts and the rule books not held. A split that cannot occur
    for this review is None, never 0 (CLAUDE.md rule 4); a count of 0 is a real count of nothing found."""
    tiles: dict[str, dict] = {}
    for tile in TILES:
        mine = [p for p in points if p["tile"] == tile]
        split = Counter(p.get("firm") for p in mine)
        entry: dict = {
            "label": TILE_WORDS[tile],
            "total": len(mine),
            "counts": "points on this page of the list",
        }
        if tile in ("not_met", "met"):
            entry["two_readers"] = (
                split.get("two readers agree", 0) if two_reader_possible else None
            )
            entry["one_reader"] = split.get("one reader", 0)
            entry["proven_by_code"] = split.get("proven by code", 0)
        elif tile == "questions":
            entry["groups"] = len({p["group_key"] or p["id"] for p in mine})
        else:
            entry["proven_by_code"] = (
                None  # a "does not apply" is never a compared value
            )
        tiles[tile] = entry
    # ONE chip per rule book: by the book's identity (its document id), never by a display string. A point that cites several clauses
    # of one book counts once for that book; a point that cites two books counts once for each; the name is the book's own.
    named: Counter = Counter()
    names: dict[str, str] = {}
    for p in points:
        seen: set[str] = set()
        for b in p.get("books") or []:
            if b["id"] in seen:
                continue
            seen.add(b["id"])
            named[b["id"]] += 1
            names[b["id"]] = b["name"]
    several = sum(1 for p in points if len({b["id"] for b in p.get("books") or []}) > 1)
    unnamed = sum(
        1
        for p in points
        if p.get("_other_books")
        or (not p.get("books") and (p.get("_book_docs") or p.get("_book_doc")))
    )
    no_book = sum(
        1
        for p in points
        if not p.get("books") and not (p.get("_book_docs") or p.get("_book_doc"))
    )
    rows_of = not_held_rows(not_held, points)
    to_confirm = [p for p in points if p.get("rank") == 9]
    confirmed = sum(1 for p in to_confirm if (p.get("decision") or {}).get("state") == "keep")
    out = {
        "tiles": tiles,
        # owner on PR #1872: the lines the AI thinks do not apply, counted apart from the four tiles
        "not_applicable_to_confirm": {
            "label": not_applicable.TITLE,
            "total": len(to_confirm),
            "confirmed": confirmed,
            "open": len(to_confirm) - confirmed,
            "sentence": not_applicable.count_line(len(to_confirm), confirmed) if to_confirm else None,
        },
        "total": len(points),
        "total_counts": "points of this paper's review (the rule check and the AI review together)",
        "rule_books": [
            {"id": i, "name": names[i], "points": c}
            for i, c in sorted(
                named.items(), key=lambda kv: (-kv[1], names[kv[0]], kv[0])
            )
        ],
        "no_rule_book_points": no_book,
        "several_books_points": several,  # counted under EACH of its books, so the chips can add up to more than the total
        "other_rule_books_points": unnamed,
        "other_rule_books_note": "points on rule books you may not read: counted, not named"
        if unnamed
        else None,
        "not_held": {
            "names": not_held[:3],
            "more": max(0, len(not_held) - 3),
            "total": len(not_held),
            "note": "Not checked, rule book not held" if not_held else None,
            # FTU-16: the two sources apart, the same split the CRS sheet "Rule books not held" states
            "on_rows": sum(1 for n in rows_of.values() if n),
            "scope_only": sum(1 for n in rows_of.values() if not n),
        },
    }
    if decided is not None:
        out["decided"], out["decided_of"] = decided, len(points)
    return out


# ------------------------------------------------------------------------------------------------ reading the stored review


def _book_of(conn, run_id: str) -> dict[str, tuple[str | None, str | None]]:
    return {
        r["rule_key"]: (r["standard_document_id"], r["rule_book"])
        for r in conn.execute(
            "SELECT rule_key, standard_document_id, rule_book FROM agent_review_rule WHERE run_id = ? AND asked = 1",
            (run_id,),
        )
    }


def stored_class_wins(line: dict, row) -> dict:
    """The class and the word the run STORED for a line (`agent_review_line.verdict_class` and `word`, written through the one exit
    that refuses an unproven Pass) are the line's class. The line's own json keeps the label it had BEFORE that exit: a Pass the
    exit would not stand behind is stored as "AI thinks: met", and the json still says "Proven by code" / "Pass". Read from the json
    alone, such a line was a Question on the page and a Pass on the older sheet (K4: 4 lines of the valve review). Here the stored
    class decides, so the page, the points list and the one CRS file all say what the run stored."""
    from . import agent_review_wording as wording

    out = dict(line)
    cls, word = row["verdict_class"], row["word"]
    if cls:
        out["verdict_class"] = cls
        if cls in (wording.CLASS_OPINION, wording.CLASS_UNAPPROVED) and word:
            out["verdict_label"] = word
    return out


def library_of(conn):
    from .agent_review_rules import library_of as _library_of

    return _library_of(conn)


def ai_points_of_run(
    conn, run_id: str, paper_document_id: str, readable: frozenset[str]
) -> tuple[list[dict], list[str]]:
    """(the points of one AI review run, the names of the rule books it did not hold). A run that is there but whose lines cannot be
    read (a missing table, a locked database) RAISES: no caller may read "could not look" as "no points" (the sign gate refuses)."""
    stored = [
        stored_class_wins(
            {**json.loads(r["line_json"] or "{}"), "item_id": r["item_id"]}, r
        )
        for r in conn.execute(
            "SELECT item_id, verdict_class, word, line_json FROM agent_review_line WHERE run_id = ? ORDER BY rowid",
            (run_id,),
        )
    ]
    held = [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM agent_review_missing_book WHERE run_id = ? ORDER BY name",
            (run_id,),
        )
    ]
    lines = words.read_now(
        stored, [{"rule_book": n} for n in held]
    )  # the one reading of every CRS (order 14)
    documents = frozenset(r[0] for r in conn.execute("SELECT id FROM documents"))
    ctx = {
        "run_id": run_id,
        "run_engine": crs_ai_header.run_engine(conn, run_id),  # FTU-17: what the run stored
        "paper_document_id": paper_document_id,
        "book_of": _book_of(conn, run_id),
        "readable": readable,
        "library": library_of(conn),  # the held books: the AI's free text is tested against the ones the viewer may not read
        "everything": documents <= readable,
        "documents": documents,  # the held documents: a line's own stored book counts only when it is one of them
    }
    return [p for p in (ai_point(ln, ctx) for ln in lines) if p is not None], held


def build(ai: list[dict], rule: list[dict], added: list[dict]) -> list[dict]:
    """The merged, ordered, grouped list (pure)."""
    return with_groups(order_points([*rule, *ai, *added]))


def public(point: dict) -> dict:
    """The point as the route returns it: private keys (leading underscore) removed."""
    return {k: v for k, v in point.items() if not k.startswith("_")}


def by_rule_book(points: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for p in points:
        out[p.get("rule_book") or ""].append(p)
    return out


def removed_stub(finding: dict, ctx: dict, *, strength: str = "unknown") -> dict:
    """A rule-check point an engineer removed: its row has left the sheet, so the list keeps it from the finding (name, page, the
    required action), with no quote. The record of a removal is never dropped."""
    page = finding.get("contractor_page")
    page = (
        page
        if isinstance(page, int) and not isinstance(page, bool) and page >= 1
        else None
    )
    rank = (
        1
        if str(finding.get("compliance_status") or "").upper() == "NON_COMPLIANT"
        else 4
    )
    # The rule book's own words are the book's (rule 5): a stub never carries the requirement text, and carries the required action only
    # when the caller may read the book it came from.
    book_ok = finding.get("standard_document_id") in ctx["readable"]
    return {
        "id": f"rc:{finding['id']}", "source": SOURCE_RULE_CHECK, "source_words": SOURCE_WORDS[SOURCE_RULE_CHECK], "engine": ENGINE_RC,
        "rank": rank, "tile": TILE_OF_RANK[rank], "firm": RANKS[rank][1] or None, "other_kind": None,
        "name": _plain(finding.get("matched_phrase")) or "A point of the rule check",
        "page": page, "rule_book": None, "clause": None, "action": (_plain(finding.get("required_action")) or None) if book_ok else None,
        "paper_quote": None, "clause_quote": None, "paper_quote_note": NO_PAPER_QUOTE, "clause_quote_note": NO_CLAUSE_QUOTE,
        "route_note": None, "view_page": _view_page(ctx.get("paper_document_id"), page), "shall": strength != "should", "strength_unknown": strength == "unknown", "group_key": None, "tags": [],
        "added_by": None, "finding_ids": [finding["id"]], "_book_doc": finding.get("standard_document_id"),
        "_book_docs": [finding["standard_document_id"]] if finding.get("standard_document_id") else [],
    }  # fmt: skip
