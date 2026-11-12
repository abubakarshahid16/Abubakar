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

from . import crs_ai_words as words

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
NO_BOOK_ACCESS = "The rule book is not one you may read, so its text is not shown."
PAPER_CHECK = "Checked by code: found on the page."
CLAUSE_CHECK = "Checked by code: found in the clause."
PASSAGE_PAPER_CHECK = "Checked by code: this passage is on the page."
PASSAGE_CLAUSE_CHECK = "Checked by code: this passage is in the clause."
ROUTE_INDEPENDENT = "Two readers reached this verdict independently."
ROUTE_SAW_FIRST = "A second reader checked this verdict and saw the first answer."
ENGINE_AI = "AI reviewer on Claude"
ENGINE_RC = "Rule check"


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


# ------------------------------------------------------------------------------------------------ a name is the field, not its tags

_BRACKETS = re.compile(r"\s*[(\[{]([^()\[\]{}]*)[)\]}]")
_TAG_ITEM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-/._]*$")
_ONE_TAG = re.compile(r"^[A-Za-z]{1,6}-\d[\w\-./]*$")
_MORE = re.compile(r"^(?:\.{2,}|\u2026|etc\.?|(?:and\s+)?\+?\d+\s+more)$", re.I)


def _is_tag_list(inner: str) -> list[str] | None:
    """The items of a bracketed group when it is a list of equipment tags (every item one token with a letter and a digit, two or more
    of them, or one that looks like a tag with its dash); None for a unit or a note like "(barg)" or "(2 mm)". General: it looks at
    the shape of the group, never at one paper's tag scheme."""
    parts = [x.strip() for x in re.split(r"[,;]|\band\b|\+(?=\s*[A-Za-z0-9])", inner) if x.strip()]
    items = [x for x in parts if not _MORE.match(x)]
    if not items:
        return None
    if not all(
        _TAG_ITEM.match(x) and any(c.isdigit() for c in x) and any(c.isalpha() for c in x)
        for x in items
    ):
        return None
    if len(items) == 1 and not _ONE_TAG.match(items[0]):
        return None
    return items


def split_tags(name: str) -> tuple[str, list[str]]:
    """(the name with every bracketed list of equipment tags taken off, the tags in the order they stood). The tags belong in the
    opened point ("Applies to: N tags"), never in the collapsed row's name."""
    tags: list[str] = []

    def take(m: re.Match) -> str:
        got = _is_tag_list(m.group(1))
        if got is None:
            return m.group(0)
        tags.extend(got)
        return ""

    clean = _BRACKETS.sub(take, str(name or ""))
    return _clean(clean), list(dict.fromkeys(tags))


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


def ai_point(line: dict, ctx: dict) -> dict | None:
    """One AI line as a point; None for a line that is not a point (a rule book not held). `ctx`: run_id, paper_document_id,
    book_of (item id -> (document id, name)), readable (frozenset of document ids the caller may read)."""
    from . import agent_review_crs as arc
    from . import crs_ai_workbook as wb
    from .agent_review_two_reader import is_independent

    rank, status, order = rank_of_ai_line(line)
    if rank == 0:
        return None
    item = str(line.get("item_id") or "")
    book_doc, _name = ctx["book_of"].get(item, (None, None))
    book_name = (
        _plain(line.get("standard"))
        if book_doc and book_doc in ctx["readable"]
        else None
    )
    clause = _clean(line.get("clause")) or None
    quotes = line.get("quotes_checked") or {}
    paper_q = (
        _clean(line.get("paper_quote"))
        if quotes.get("paper") and _clean(line.get("paper_quote"))
        else None
    )
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
    field, tags = split_tags(wb.field_name(line))
    name = (
        _plain(field)
        or (_plain(arc.against(line)) if book_name else "")
        or "A point of the AI review"
    )
    reason = line.get("reason_code") or ""
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
        "engine": ENGINE_AI,
        "rank": rank,
        "tile": TILE_OF_RANK[rank],
        "firm": RANKS[rank][1] or None,
        "other_kind": other_kind,
        "name": name,
        "page": page,
        "rule_book": book_name,
        "clause": clause if book_name else None,
        "action": action or None,
        "paper_quote": paper_q,
        "clause_quote": clause_q,
        "paper_quote_note": PAPER_CHECK if paper_q else NO_PAPER_QUOTE,
        "clause_quote_note": CLAUSE_CHECK
        if clause_q
        else (NO_CLAUSE_QUOTE if book_readable else NO_BOOK_ACCESS),
        "route_note": (ROUTE_INDEPENDENT if is_independent(line) else ROUTE_SAW_FIRST)
        if two_readers
        else None,
        "view_page": _view_page(ctx.get("paper_document_id"), page),
        "shall": not bool(line.get("recommendation")),
        "group_key": group_key(
            SOURCE_AI_REVIEW,
            rank,
            book_doc if book_name else None,
            clause,
            str(reason),
            _plain(field),
        ),
        "tags": tags,
        "added_by": None,
        "_book_doc": book_doc,
        "_book_docs": [book_doc] if book_doc else [],
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


def rule_point(
    row: dict,
    ctx: dict,
    finding: dict | None,
    sides: dict,
    *,
    strength: str = "unknown",
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
    book_name = (
        _plain(row.get("standard_reference"))
        if book_doc and book_doc in ctx["readable"]
        else None
    )
    paper_q = (
        _clean((finding or {}).get("contractor_evidence_text"))
        if side_p.get("verified") and finding
        else ""
    )
    clause_q = (
        _clean((finding or {}).get("requirement_source_text"))
        if side_s.get("verified") and finding
        else ""
    )
    reason = (finding or {}).get("reason_code") or kind or ""
    field, tags = split_tags(section.split(" - ", 1)[-1] if " - " in section else section)
    name = (
        _plain(field)
        or _plain(" ".join(comment.split()[:7]))
        or "A point of the rule check"
    )
    return {
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
        "clause": None,
        "action": _plain(comment) or None,
        "paper_quote": paper_q or None,
        "clause_quote": clause_q or None,
        "paper_quote_note": PASSAGE_PAPER_CHECK if paper_q else NO_PAPER_QUOTE,
        "clause_quote_note": PASSAGE_CLAUSE_CHECK if clause_q else NO_CLAUSE_QUOTE,
        "route_note": None,
        "view_page": _view_page(ctx.get("paper_document_id"), page),
        "shall": strength != "should",
        "strength_unknown": strength == "unknown",
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
        "_row_key": key,
    }


def order_points(points: list[dict]) -> list[dict]:
    """Worst first: by rank, then a 'shall' rule before a 'should' rule, then the order they came in (stable)."""
    return [
        p
        for _i, p in sorted(
            enumerate(points),
            key=lambda ip: (ip[1]["rank"], 0 if ip[1].get("shall", True) else 1, ip[0]),
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
        1 for p in points if not p.get("books") and (p.get("_book_docs") or p.get("_book_doc"))
    )
    no_book = sum(
        1 for p in points if not p.get("books") and not (p.get("_book_docs") or p.get("_book_doc"))
    )
    out = {
        "tiles": tiles,
        "total": len(points),
        "total_counts": "points of this paper's review (the rule check and the AI review together)",
        "rule_books": [
            {"id": i, "name": names[i], "points": c}
            for i, c in sorted(named.items(), key=lambda kv: (-kv[1], names[kv[0]], kv[0]))
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


def ai_points_of_run(
    conn, run_id: str, paper_document_id: str, readable: frozenset[str]
) -> tuple[list[dict], list[str]]:
    """(the points of one AI review run, the names of the rule books it did not hold). A run that is there but whose lines cannot be
    read (a missing table, a locked database) RAISES: no caller may read "could not look" as "no points" (the sign gate refuses)."""
    lines = [
        {**json.loads(r["line_json"] or "{}"), "item_id": r["item_id"]}
        for r in conn.execute(
            "SELECT item_id, line_json FROM agent_review_line WHERE run_id = ? ORDER BY rowid",
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
    ctx = {
        "run_id": run_id,
        "paper_document_id": paper_document_id,
        "book_of": _book_of(conn, run_id),
        "readable": readable,
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
