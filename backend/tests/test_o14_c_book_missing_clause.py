"""Order 14 lane C (C1): a point whose rule book is not held always says WHICH clause, or plainly "clause not named by the reviewer";
never a blank, and never "no rule book cited" for a row that cites a book. One home: `review_points.book_missing_words`, read by the
action, the reason and both rule-book cells of the team file. Invented books and findings only."""

from __future__ import annotations

import io

from openpyxl import load_workbook

from app import crs_one, review_points
from app import review_points_content as content
from app import review_points_service as svc
from tests.test_b1_review_points import world_with_both
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture
from tests.test_k4_one_crs import on, scope_all  # noqa: F401 - fixtures and helpers

CTX = {"run_id": "r", "paper_document_id": "p", "readable": frozenset({"p"}), "_library": []}


def _point(n: int, kind: str, reference: str, clause: str = "", comment: str = "Plan 52 is required."):
    row = {"row_kind": kind, "finding_id": f"bm-{n}", "page_section": f"p.{n} - Seal plan {n}", "comment": comment,
           "standard_reference": reference, "priority": "High"}  # fmt: skip
    finding = {"standard_document_id": None, "standard_clause": clause, "requirement": "Plan 52 shall be used.",
               "requirement_source_text": "Plan 52 shall be used.", "reason_code": "NON_COMPLIANT"}  # fmt: skip
    return review_points.rule_point(row, CTX, finding, {}, proof=(True, True))


def test_the_words_name_the_clause_or_say_plainly_it_was_not_named():
    w = review_points.book_missing_words
    assert w("BOOK-77", "8.5") == "Book missing: BOOK-77, clause 8.5"
    assert w("BOOK-77 6.1", "") == "Book missing: BOOK-77 6.1"  # the stored reference already holds the clause
    assert w("BOOK-77 (edition not recorded) cl. 5.2", "") == "Book missing: BOOK-77 (edition not recorded) cl. 5.2"
    assert w("BOOK-77", "") == "Book missing: BOOK-77 (clause not named by the reviewer)"
    assert w("IEC 99001; IEC 99002-3", "") == "Book missing: IEC 99001; IEC 99002-3 (clause not named by the reviewer)"
    assert w("API 9999 2017", "") == "Book missing: API 9999 2017 (clause not named by the reviewer)"  # an edition year is no clause
    # an edition or revision number is no clause either (review R1 of PR #1863)
    for ref in ("API 9999 11th edition", "API 9998 7th", "Spec 12-AB rev 3", "XS-1 Rev. B2", "XS-2 edition 5"):
        assert w(ref, "") == f"Book missing: {ref} (clause not named by the reviewer)", ref
    assert w("XS-1 11th edition 6.1", "") == "Book missing: XS-1 11th edition 6.1"  # a clause beside an edition is still a clause


def test_a_point_with_no_clause_says_so_in_its_action_and_reason():
    p = _point(1, "ai_engineering_check", "BOOK-77; BOOK-78")
    assert p["reason_words"] == "Book missing: BOOK-77; BOOK-78 (clause not named by the reviewer)"
    assert p["action"].startswith("Book missing: BOOK-77; BOOK-78 (clause not named by the reviewer).")
    assert p["clause"] is None and p["rule_text"] is None  # still no clause cell and no rule words of a book not held (G7)


def test_the_built_team_file_names_the_clause_in_every_book_missing_row():
    doc, _rc, _ai, _client = world_with_both()
    listing, raw, extra = svc.export_listing(doc, scope_all())
    added = [
        _point(1, "ai_engineering_check", "BOOK-77; BOOK-78"),  # no clause anywhere
        _point(2, "clause_review", "BOOK-79", clause="8.5"),  # the clause only in the finding
        _point(3, "playbook_check", "BOOK-80 6.1"),  # the clause in the reference
    ]
    raw = [*raw, *added]
    data = crs_one.build_team(doc, scope_all(), listing_raw=({**listing, "of": len(raw)}, raw, extra))
    wb = load_workbook(io.BytesIO(data))
    want = {
        "BOOK-77": "Book missing: BOOK-77; BOOK-78 (clause not named by the reviewer)",
        "BOOK-79": "Book missing: BOOK-79, clause 8.5",
        "BOOK-80": "Book missing: BOOK-80 6.1",
    }
    ev = [list(r) for r in wb[crs_one.EVIDENCE_SHEET].iter_rows(values_only=True)]
    hi = next(i for i, r in enumerate(ev) if r and r[0] == "No")
    head = ev[hi]
    rows = [dict(zip(head, r)) for r in ev[hi + 1 :] if r and r[0] is not None]
    for book, words in want.items():
        mine = [r for r in rows if book in str(r["Reason"] or "")]
        assert len(mine) == 1, book
        r = mine[0]
        assert r["Reason"] == words and str(r["What the contractor must do"]).startswith(words + ".")
        assert r["Rule book"] == words  # it cites a book: never "no rule book cited"
    # W-D6 (order 14, 17 Nov 2026): a book-missing point carries no finding, so it is NOT a comment: it stands on the sheet "Not a
    # comment" (its rule-books cell names the book and the clause there) and is counted with the books not held
    comments = [list(r) for r in wb[crs_one.TEAM_SHEET].iter_rows(values_only=True)]
    ci = next(i for i, r in enumerate(comments) if r and r[0] == "Comment")
    col = comments[ci].index("Rule books and clauses")
    cells = [str(r[col]) for r in comments[ci + 1 :] if r and r[0] is not None]
    assert not any(w in c for w in want.values() for c in cells)
    aside = [list(r) for r in wb[crs_one.NOT_A_COMMENT_SHEET].iter_rows(values_only=True)]
    ai = next(i for i, r in enumerate(aside) if r and r[0] == "Field or item")
    acol = aside[ai].index("Rule books and clauses")
    aside_cells = [str(r[acol]) for r in aside[ai + 1 :] if r and r[0] is not None]
    for words in want.values():
        assert words in aside_cells
    assert content.NO_RULE_CITED not in cells  # every comment of this file cites a book (held, or missing and said so)
    from app import crs_completeness

    assert crs_completeness.cut_report(data, raw)["problems"] == []  # the download check reads the same words as the file
    # the scorer reads the books the file itself says are missing from the same words
    from tools import answer_key_score as aks

    path = io.BytesIO(data)
    assert {"BOOK-77", "BOOK-78", "BOOK-79", "BOOK-80"} <= aks.not_held_books(path)
