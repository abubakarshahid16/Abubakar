"""Order 14 lane D, 17 Nov 2026: the CRS gates that failed on a fresh pump review. Invented data only.

1. G1 (honesty rule 4): a point's stored rule words are shown as the book's words only where code finds them in the linked book's
   stored pages; words that stand in the book with the book's own lines between them (a running header over a page break) are shown
   in pieces with a visible mark; words the book does not hold (an AI step's own wording) are never shown as the book's.
2. G3: an AI "met" made a Query only by a pass-guard objection of code's own reach (the rule's field is not known), with both quotes
   verified by code, is "AI says met, not confirmed: engineer to tick", never a comment; the gate reads every guard code as a pass
   reason.
3. G4: a clause a reading carried over a later heading (every rule of an annex filed under the last numbered clause before it) is no
   citation: code that places the rule's verified words outside the clause shows no clause, the page instead; the grouping still
   keys on it."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from app import agent_review_pass_guards as pass_guards
from app import agent_review_standards as standards
from app import crs_ai_words as words
from app import crs_comments
from app import review_points as rp
from app import subject_scope

_SPEC = importlib.util.spec_from_file_location(
    "crs_gates_d", Path(__file__).resolve().parents[2] / "scripts" / "crs_gates.py"
)
gates = importlib.util.module_from_spec(_SPEC)
sys.modules["crs_gates_d"] = gates
_SPEC.loader.exec_module(gates)

# ------------------------------------------------------------------------------------------------ invented books

HEAD = "Acme Standard ZZ-1 Issue 3 page header line"
P1 = "4.1 Scope\nOther words first. The inlet flange of every widget shall be raised face and the bolting shall be"
P2 = f"{HEAD}\nstainless steel grade nine unless the buyer agrees otherwise. More text follows here."
STORED = (
    "The inlet flange of every widget shall be raised face and the bolting shall be stainless steel grade nine unless the buyer "
    "agrees otherwise."
)


class _Books:
    """A `BookPages` stand-in: the invented book's pages, no database."""

    def __init__(self, pages: dict[int, str]) -> None:
        self._book = pass_guards.Book(pages)

    def book(self, _doc):
        return self._book


BOOKS = _Books({1: P1, 2: P2})


# --- 1. G1: book words


def test_words_over_a_page_break_with_a_header_between_are_shown_in_pieces_that_the_gate_finds():
    assert not standards.verify("doc-b", STORED, 1, BOOKS).found  # the stored words, joined, are not on any page: the defect
    shown = standards.book_words("doc-b", STORED, 1, BOOKS)
    assert shown is not None and standards.CUT_MARK in shown
    assert shown.replace(standards.CUT_MARK, " ") == STORED  # nothing of the stored words is dropped: the mark only shows the gap
    assert gates.g1_quotes([gates.Row(id="E1", quotes=(shown,), quote_docs=("doc-b",))], BOOKS).status == gates.PASS
    joined = gates.g1_quotes([gates.Row(id="E1", quotes=(STORED,), quote_docs=("doc-b",))], BOOKS)
    assert joined.status == gates.FAIL  # what the page showed before


def test_words_the_book_does_not_hold_are_never_shown_as_the_books():
    assert standards.book_words("doc-b", "Widget part reference", 1, BOOKS) is None  # an AI step's own words
    assert standards.book_words(None, STORED, 1, BOOKS) is None  # no linked book: nothing to search
    whole = "The inlet flange of every widget shall be raised face"
    assert standards.book_words("doc-b", whole, 1, BOOKS) == whole  # found whole: shown as it is


CTX = {"run_id": "r", "paper_document_id": "p", "readable": frozenset({"p", "doc-b"}), "_library": [], "_book_pages": BOOKS}  # fmt: skip
ROW = {"row_kind": "clause_review", "finding_id": "f1", "page_section": "p.3 - Flange", "comment": "Check the flange.",
       "standard_reference": "ZZ-1 (p.1)", "priority": "3"}  # fmt: skip


def _finding(text: str) -> dict:
    return {"standard_document_id": "doc-b", "standard_clause": "", "requirement_source_text": text, "requirement": text,
            "contractor_evidence_text": "RF", "standard_page": 1}  # fmt: skip


def test_a_rule_check_point_shows_only_book_words_code_finds_and_groups_on_the_stored_words():
    p = rp.rule_point(dict(ROW), CTX, _finding(STORED), {}, proof=(True, True))
    assert p["rule_text"] == standards.book_words("doc-b", STORED, 1, BOOKS) and standards.CUT_MARK in p["rule_text"]
    q = rp.rule_point(dict(ROW), CTX, _finding("Widget part reference"), {}, proof=(True, True))
    assert q["rule_text"] is None  # not in the book: never shown as its words
    assert crs_comments._requirement_of(q) == "widget part reference"  # the comment grouping keys on the stored words as before


# --- 2. G3: a met only code could not reach


def _met(**kw) -> dict:
    line = {"item_id": "R-1", "source": "rule", "verdict": "Query", "decided_by": "engineer", "ai_verdict": "Pass",
            "reason_code": "pass_field_unknown", "paper_quote": "RING OIL", "second_opinion": {"agree": True},
            "quotes_checked": {"paper": True, "clause": True, "both": True}}  # fmt: skip
    return {**line, **kw}


def _point(line: dict) -> dict:
    return {"id": "ai:r:R-1", "rank": 4, "tile": "questions", "name": None, "rule_book": "ZZ-1", "clause": "4.1", "_line": line}


def test_a_met_held_only_by_code_reach_is_ticked_never_a_comment():
    for code in crs_comments.REACH_ONLY_GUARDS:
        line = _met(reason_code=code)
        assert crs_comments.tick_only(_point(line))
        (aside,) = crs_comments.set_aside([_point(line)])
        assert aside[1] == words.KIND_MET_NOT_CONFIRMED and crs_comments.group([_point(line)]) == []


def test_a_met_with_a_doubt_about_the_paper_or_the_quote_stays_a_comment():
    kept = [
        _met(quotes_checked={"paper": False, "clause": True}),  # the paper quote not verified
        _met(quotes_checked={"paper": True, "clause": False}),  # two doubts: the clause quote too
        _met(second_opinion={"agree": False}),  # the readers disagree
        _met(paper_quote="By Contractor"),  # the value is left open
        _met(reason_code="pass_field_not_quoted"),  # the guard doubts the quote itself
        _met(ai_verdict="Fail", reason_code="field_unknown_cannot_check_deferral"),  # not an AI "met"
    ]
    for line in kept:
        assert not crs_comments.tick_only(_point(line)), line


def test_gate_g3_reads_every_guard_code_as_a_pass_reason():
    row = gates.Row(id="C1", rank=4, reason="field_unknown_cannot_check_deferral")
    assert gates.no_comment_class(row) == "pass reason"
    assert gates.no_comment_class(gates.Row(id="C1", rank=4, reason="field_unknown_cannot_check_deferral", open_question="x")) is None
    assert gates.no_comment_class(gates.Row(id="C1", rank=4, reason="absent")) is None


# --- 3. G4: a clause that does not hold the rule's words

BOOK_TEXT = [
    (1, "1 Scope\nThis book covers widgets.\n2 Testing\n2.1 Hydrotest\nThe casing of every firewater widget shall be hydrotested at"
        " one and a half times the design pressure."),
    (2, "3 Cost evaluation\nBids shall be compared on the whole life cost of the widget over twenty years of service."),
]  # fmt: skip
HYDRO = "The casing of every firewater widget shall be hydrotested at one and a half times the design pressure."
COST = "Bids shall be compared on the whole life cost of the widget over twenty years of service."


def _texts() -> dict:
    return {"doc-c": subject_scope.StandardText(BOOK_TEXT)}


def test_clause_holds_reads_the_books_own_headings():
    assert standards.clause_holds("doc-c", "2.1", HYDRO, 1, _texts()) is True
    assert standards.clause_holds("doc-c", "2.1", COST, 2, _texts()) is False  # filed under 2.1 by a reading; it stands under 3
    assert standards.clause_holds("doc-c", "9.9", COST, 2, _texts()) is None  # no heading of the clause: code cannot tell
    assert standards.clause_holds("doc-c", "2.1", "Words that are not in the book at all, anywhere.", 2, _texts()) is None


def _line(clause_quote: str, page: int) -> dict:
    return {"item_id": "R-2", "source": "rule", "standard": "ZZ-1", "clause": "2.1", "clause_page": 1, "standard_document_id": "doc-c",
            "clause_quote": clause_quote, "requirement": clause_quote, "verdict": "Query", "ai_verdict": "Query",
            "quotes_checked": {"paper": True, "clause": True}, "clause_book": {"found": True, "page": page}}  # fmt: skip


def test_a_clause_that_does_not_hold_the_rules_words_is_not_cited():
    texts = _texts()

    def holds(doc, clause, text, page):
        return standards.clause_holds(doc, clause, text, page, texts)

    (moved,) = words.mark_clause_unconfirmed([_line(COST, 2)], holds)
    assert moved["clause"] == "" and moved["clause_page"] is None and moved[words.CLAUSE_UNCONFIRMED_KEY] == "2.1"
    assert moved["verdict"] == "Query"  # the verdict is untouched
    assert words.mark_clause_unconfirmed([moved], holds) == [moved]  # idempotent: every reader reads it again
    (kept,) = words.mark_clause_unconfirmed([_line(HYDRO, 1)], holds)
    assert kept["clause"] == "2.1" and words.CLAUSE_UNCONFIRMED_KEY not in kept
    unverified = {**_line(COST, 2), "quotes_checked": {"paper": True, "clause": False}}
    assert words.mark_clause_unconfirmed([unverified], holds)[0]["clause"] == "2.1"  # not judged: the quote is not verified

    from app import agent_review_crs as arc

    assert arc.against(moved) == f"ZZ-1 page 2 ({words.CLAUSE_NOT_CONFIRMED})"
    point = {"id": "ai:r:R-2", "name": None, "rule_book": "ZZ-1", "clause": "", "_line": moved}
    assert crs_comments._rule_of(point)[1] == crs_comments._clause_key("2.1")  # one rule still groups as one rule


def test_a_rule_check_clause_that_does_not_hold_its_words_is_not_cited():
    ctx = {**CTX, "readable": frozenset({"p", "doc-c"}), "_book_texts": _texts()}
    finding = {**_finding(COST), "standard_document_id": "doc-c", "standard_clause": "2.1", "standard_page": 2}
    p = rp.rule_point({**ROW, "standard_reference": "ZZ-1"}, ctx, finding, {}, proof=(True, True))
    assert p["clause"] is None and p["_clause_unconfirmed"] == "2.1"
    ok = rp.rule_point({**ROW, "standard_reference": "ZZ-1"}, ctx, {**finding, "requirement_source_text": HYDRO, "standard_page": 1},
                       {}, proof=(True, True))  # fmt: skip
    assert ok["clause"] == "2.1" and ok["_clause_unconfirmed"] is None


def test_every_reader_reads_the_clause_rule_through_read_now():
    (got,) = words.read_now([_line(COST, 2)], [], holds=lambda *_a: False)
    assert got["clause"] == "" and got[words.CLAUSE_UNCONFIRMED_KEY] == "2.1"
    (same,) = words.read_now([_line(COST, 2)], [], holds=lambda *_a: None)
    assert same["clause"] == "2.1"  # code cannot tell: nothing changes


def test_an_ai_point_shows_its_unverified_rule_words_only_where_the_book_holds_them():
    ctx = {"run_id": "r", "paper_document_id": "p", "book_of": {"R-3": ("doc-b", "ZZ-1")}, "readable": frozenset({"p", "doc-b"}),
           "_book_pages": BOOKS}  # fmt: skip

    def line(text):
        return {"item_id": "R-3", "source": "rule", "standard": "ZZ-1", "clause": "4.1", "verdict": "Query", "ai_verdict": "Query",
                "standard_document_id": "doc-b", "requirement": text, "quotes_checked": {"paper": True, "clause": False}}  # fmt: skip

    assert rp.ai_point(line(STORED), ctx)["rule_text"] == standards.book_words("doc-b", STORED, None, BOOKS)
    assert rp.ai_point(line("Widget part reference"), ctx)["rule_text"] is None
