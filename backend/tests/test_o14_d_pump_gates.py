"""Order 14 lane D, 17 Nov 2026: the CRS gates that failed on a fresh pump review. Invented data only.

1. G1 (honesty rule 4): a point's stored rule words are shown as the book's words only where code finds them in the linked book's
   stored pages; words split ONLY by a page break with the book's running header and footer and the page number between are shown
   in pieces with a visible mark (whole words, at most three pieces, each long enough for the matcher); a word of the book between
   two pieces (a "not"), pieces far apart, a cut inside a number: never shown as the book's.
2. G3: an AI "met" made a Query only by a pass-guard objection of code's own reach (the rule's field is not known), with both quotes
   verified by code, is "AI says met, not confirmed: engineer to tick", never a comment; the gate reads every guard code as a pass
   reason.
3. G4: a clause a reading carried over a later heading (every rule of an annex filed under the last numbered clause before it) is no
   citation. The clause is removed ONLY when code is certain (a titled end of the clause's own family on the words' own page, at
   every place the words stand); a heading that only MAY end it marks the clause "not checked", never "the words are not in it"; a
   contents page proves nothing; rules that open alike are judged where their own words stand. The grouping still keys on it."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from app import agent_review_pass_guards as pass_guards
from app import agent_review_standards as standards
from app import crs_ai_words as words
from app import crs_comments
from app import review_points as rp

_SPEC = importlib.util.spec_from_file_location(
    "crs_gates_d", Path(__file__).resolve().parents[2] / "scripts" / "crs_gates.py"
)
gates = importlib.util.module_from_spec(_SPEC)
sys.modules["crs_gates_d"] = gates
_SPEC.loader.exec_module(gates)

# ------------------------------------------------------------------------------------------------ invented books

HEAD = "Acme Standard ZZ-1 Issue 3 page header line"
FOOT = "Acme Widget Committee - company use only"


def _page(n: int, body: str) -> str:
    """An invented book page: the running header and footer of every page, the page's own number, and its body."""
    return f"{HEAD}\nPage {n} of 9\n{body}\n{FOOT}\n{n}"


P1 = "4.1 Scope\nOther words first. The inlet flange of every widget shall be raised face and the bolting shall be"
P2 = "stainless steel grade nine unless the buyer agrees otherwise. More text follows here."
STORED = (
    "The inlet flange of every widget shall be raised face and the bolting shall be stainless steel grade nine unless the buyer "
    "agrees otherwise."
)
P3 = ("Every drain valve shall not be installed below the casing centre line of the widget.\n"
      "The flange gasket thickness shall be 50 mm for every widget size.\n"
      "The seal flush plan shall be agreed with the buyer before the order\nis placed. Other words of the book stand here.")  # fmt: skip
SHORT_TAIL = ("4.3 Bolting\nAll bolting of the casing joints of the widget shall be of stainless steel", "grade nine or finer\nMore.")
EXACT_TAIL = ("4.4 Studs\nAll studs of the bearing housing of the widget shall be of stainless steel", "grade nine or better\nMore.")
FRAGMENTS = ["The first part of a long rule on the widget", "runs on over the second page break of", "the book and on over the third",
             "page break to its end here."]  # fmt: skip


class _Books:
    """A `BookPages` stand-in: the invented book's pages, no database."""

    def __init__(self, pages: dict[int, str]) -> None:
        self._book = pass_guards.Book(pages)

    def book(self, _doc):
        return self._book


BOOKS = _Books({1: _page(1, P1), 2: _page(2, P2), 3: _page(3, P3), 4: _page(4, "Nothing of note.")})


def _book_of(*bodies: str) -> _Books:
    """A book whose pages 1.. hold `bodies`, padded to five pages so its header and footer are running lines."""
    bodies = bodies + ("Padding text of the book.",) * max(0, 5 - len(bodies))
    return _Books({n: _page(n, body) for n, body in enumerate(bodies, start=1)})


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


def test_a_word_the_book_has_between_two_pieces_is_never_skipped():
    # the book says "shall not be installed": the stored words without the "not" are not the book's words, in pieces or whole
    assert standards.book_words("doc-b", "Every drain valve shall be installed below the casing centre line of the widget.", 3,
                                BOOKS) is None  # fmt: skip


def test_pieces_far_apart_on_one_page_or_on_pages_apart_are_never_joined():
    same_page = "The flange gasket thickness shall be 50 mm for every widget size. Other words of the book stand here."
    assert standards.book_words("doc-b", same_page, 3, BOOKS) is None  # the book's own sentence stands between: not a page break
    pages_apart = "The inlet flange of every widget shall be raised face and the bolting shall be Nothing of note."
    assert standards.book_words("doc-b", pages_apart, 1, BOOKS) is None  # page 1, then page 4: not the next page


def test_a_number_is_never_cut_inside_its_digits():
    assert standards.book_words("doc-b", "The flange gasket thickness shall be 5 mm for every widget size.", 3, BOOKS) is None
    assert standards.book_words("doc-b", "The flange gasket thickness shall be 50 mm for every widget", 3, BOOKS) is not None


def test_a_running_line_inside_a_page_is_never_a_gap():
    body = f"The widget seal shall be of the double cartridge type with a\n{HEAD}\nbarrier fluid system fitted by the maker of the seal."
    books = _book_of(body)
    text = "The widget seal shall be of the double cartridge type with a barrier fluid system fitted by the maker of the seal."
    assert standards.book_words("doc-r", text, 1, books) is None  # the header line sits inside the page: not a page break


def test_a_cut_inside_a_word_or_a_number_at_either_end_is_never_shown():
    books = _book_of("The inlet flange of every widget shall be raised face and the bolting shall be",
                     "stainless steel grade nine and 150 mm long in every case.")  # fmt: skip
    head = "The inlet flange of every widget shall be raised face and the bolting shall be stainless steel grade nine and"
    assert standards.book_words("doc-w", f"{head} 150 mm long", 1, books) is not None
    assert standards.book_words("doc-w", f"{head} 15", 1, books) is None  # "15" of "150"
    assert standards.book_words("doc-w", "he inlet flange of every widget shall be raised face and the bolting shall be stainless steel",
                                1, books) is None  # fmt: skip  ("he" of "The")


def test_every_piece_is_at_least_the_matchers_off_page_minimum():
    for (first, tail), ok in ((SHORT_TAIL, False), (EXACT_TAIL, True)):
        books = _book_of(first, tail)
        text = f"{first.split(chr(10), 1)[1]} {tail.split(chr(10))[0]}"
        assert len(tail.split(chr(10))[0]) == pass_guards.OFF_PAGE_MIN - (0 if ok else 1)
        got = standards.book_words("doc-x", text, 1, books)
        assert (got is not None) is ok, text
        if ok:
            assert gates.g1_quotes([gates.Row(id="E1", quotes=(got,), quote_docs=("doc-x",))], books).status == gates.PASS


def test_at_most_three_pieces():
    books = _book_of(*FRAGMENTS)
    three = standards.book_words("doc-y", " ".join(FRAGMENTS[:3]), 1, books)
    assert three is not None and three.count(standards.CUT_MARK.strip()) == standards.MOST_PIECES - 1
    assert standards.book_words("doc-y", " ".join(FRAGMENTS), 1, books) is None  # four pieces: not shown as the book's


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
        " one and a half times the design pressure.\n2.2 Painting\nThe casing of every widget shall be painted with two coats of"
        " epoxy paint."),
    (2, "3 Cost evaluation\nBids shall be compared on the whole life cost of the widget over twenty years of service."),
]  # fmt: skip
HYDRO = "The casing of every firewater widget shall be hydrotested at one and a half times the design pressure."
PAINT = "The casing of every widget shall be painted with two coats of epoxy paint."
COST = "Bids shall be compared on the whole life cost of the widget over twenty years of service."


def _texts() -> dict:
    return {"doc-c": standards.ClauseText(BOOK_TEXT)}


def test_clause_holds_reads_the_books_own_headings():
    assert standards.clause_holds("doc-c", "2.1", HYDRO, 1, _texts()) is True
    assert standards.clause_holds("doc-c", "2.1", PAINT, 1, _texts()) is False  # 2.2 titled on the same page: a certain end
    # "3" may end 2.1 but is not of its family: the clause is not checked, never called wrong
    assert standards.clause_holds("doc-c", "2.1", COST, 2, _texts()) == standards.CLAUSE_UNSURE
    assert standards.clause_holds("doc-c", "9.9", COST, 2, _texts()) is None  # no heading of the clause: code cannot tell
    assert standards.clause_holds("doc-c", "2.1", "Words that are not in the book at all, anywhere.", 2, _texts()) is None


# the pump case, invented: a contents page that is not read as one (ids alone on their lines, titles below, no page numbers), and
# a body page whose headings are ids alone on their lines too; the rule's words stand between the body's "2.3" and "3"
CONTENTS = "Contents\n2.2\nPump Tests\n2.3\nFirewater Tests\n3\nLife Cycle Cost\nAppendix A\nData Forms"
BODY = ("2.2\nThe widget shall be tested at the works of the maker.\n2.3\nAll casing parts of every firewater widget shall be"
        " hydrotested as one assembly for ten minutes.\n3\nLife Cycle Cost\nBids for large widgets shall be compared on the whole"
        " life cost over twenty years.")  # fmt: skip
CASING = "All casing parts of every firewater widget shall be hydrotested as one assembly for ten minutes."
BIDS = "Bids for large widgets shall be compared on the whole life cost over twenty years."


def test_a_clause_heading_on_a_body_page_holds_its_words_though_a_contents_page_names_it_first():
    texts = {"doc-p": standards.ClauseText([(3, CONTENTS), (29, BODY)])}
    assert standards.clause_holds("doc-p", "2.3", CASING, 29, texts) is True
    assert standards.clause_holds("doc-p", "2.3", BIDS, 29, texts) == standards.CLAUSE_UNSURE  # after the body's "3": may end it


# two rules that open alike, one under 4.1 and one under 4.2: the one that matches is judged, never the first hit
ALIKE = ("4.1 General Rules\nThe widget casing shall be painted with two coats of blue epoxy paint.\n4.2 Coating Rules\nThe widget"
         " casing shall be painted with two coats of blue epoxy paint where it is exposed to sea air.")  # fmt: skip
SEA = "The widget casing shall be painted with two coats of blue epoxy paint where it is exposed to sea air."


def test_rules_that_open_alike_are_judged_where_their_own_words_stand():
    texts = {"doc-a": standards.ClauseText([(7, ALIKE)])}
    assert standards.clause_holds("doc-a", "4.2", SEA, 7, texts) is True
    assert standards.clause_holds("doc-a", "4.1", SEA, 7, texts) is False  # its words stand under 4.2, titled on the same page
    opening = "The widget casing shall be painted with two coats of blue epoxy paint."
    assert standards.clause_holds("doc-a", "4.1", opening, 7, texts) is True
    assert standards.clause_holds("doc-a", "4.2", opening, 7, texts) is True  # the same words open the 4.2 rule too: every place counts


def test_a_contents_page_proves_nothing():
    contents = "Contents\n1 Scope 1\n2 Rules 1\n3 Tests 2\n4 Coats 2\n4.1 General Rules 2\n4.2 Coating Rules"
    pages = [(1, contents), (2, "The widget shall be blue in every case of its use on site."), (3, "4.1 General Rules\nOther words.")]
    texts = {"doc-k": standards.ClauseText(pages)}
    # "4.2 Coating Rules" carries no page number, but it stands on a contents page: it is no heading, so nothing decides
    assert standards.clause_holds("doc-k", "4.1", "The widget shall be blue in every case of its use on site.", 2, texts) is None


def test_a_soft_end_or_a_certain_end_on_the_page_before_is_never_proof():
    soft = "4.1 General Rules\nThe widget shall be red.\n5 Testing Rules\nEvery widget shall be tested at the works of its maker."
    texts = {"doc-s": standards.ClauseText([(4, soft)])}
    assert standards.clause_holds("doc-s", "4.1", "Every widget shall be tested at the works of its maker.", 4, texts) == (
        standards.CLAUSE_UNSURE)  # fmt: skip
    before = [(4, "4.1 General Rules\nThe widget shall be red.\n4.2 Coating Rules\nThe widget shall be blue."),
              (5, "Every widget shall be tested at the works of its maker, with its own driver.")]  # fmt: skip
    texts = {"doc-t": standards.ClauseText(before)}
    assert standards.clause_holds("doc-t", "4.1", "Every widget shall be tested at the works of its maker, with its own driver.", 5,
                                  texts) == standards.CLAUSE_UNSURE  # fmt: skip


def _line(clause_quote: str, page: int) -> dict:
    return {"item_id": "R-2", "source": "rule", "standard": "ZZ-1", "clause": "2.1", "clause_page": 1, "standard_document_id": "doc-c",
            "clause_quote": clause_quote, "requirement": clause_quote, "verdict": "Query", "ai_verdict": "Query",
            "quotes_checked": {"paper": True, "clause": True}, "clause_book": {"found": True, "page": page}}  # fmt: skip


def test_a_clause_that_does_not_hold_the_rules_words_is_not_cited():
    texts = _texts()

    def holds(doc, clause, text, page):
        return standards.clause_holds(doc, clause, text, page, texts)

    (moved,) = words.mark_clause_unconfirmed([_line(PAINT, 1)], holds)
    assert moved["clause"] == "" and moved["clause_page"] is None and moved[words.CLAUSE_UNCONFIRMED_KEY] == "2.1"
    assert words.CLAUSE_UNCHECKED_KEY not in moved  # code is certain: a titled end of the clause stands between on the page
    assert moved["verdict"] == "Query"  # the verdict is untouched
    assert words.mark_clause_unconfirmed([moved], holds) == [moved]  # idempotent: every reader reads it again
    (kept,) = words.mark_clause_unconfirmed([_line(HYDRO, 1)], holds)
    assert kept["clause"] == "2.1" and words.CLAUSE_UNCONFIRMED_KEY not in kept
    unverified = {**_line(PAINT, 1), "quotes_checked": {"paper": True, "clause": False}}
    assert words.mark_clause_unconfirmed([unverified], holds)[0]["clause"] == "2.1"  # not judged: the quote is not verified

    from app import agent_review_crs as arc

    assert arc.against(moved) == f"ZZ-1 page 1 ({words.CLAUSE_NOT_CONFIRMED})"
    point = {"id": "ai:r:R-2", "name": None, "rule_book": "ZZ-1", "clause": "", "_line": moved}
    assert crs_comments._rule_of(point)[1] == crs_comments._clause_key("2.1")  # one rule still groups as one rule


def test_a_clause_code_is_not_sure_of_is_marked_not_checked_never_wrong():
    texts = _texts()
    (doubt,) = words.mark_clause_unconfirmed([_line(COST, 2)], lambda d, c, t, p: standards.clause_holds(d, c, t, p, texts))
    assert doubt["clause"] == "" and doubt[words.CLAUSE_UNCONFIRMED_KEY] == "2.1" and doubt[words.CLAUSE_UNCHECKED_KEY] is True
    from app import agent_review_crs as arc

    shown = arc.against(doubt)
    assert shown == f"ZZ-1 page 2 ({words.CLAUSE_NOT_CHECKED.format(clause='2.1')})"
    assert words.CLAUSE_NOT_CONFIRMED not in shown  # never "the rule's words are not in it"
    assert words.mark_clause_unconfirmed([doubt], lambda *_a: False) == [doubt]  # idempotent


def test_a_rule_check_clause_that_does_not_hold_its_words_is_not_cited():
    ctx = {**CTX, "readable": frozenset({"p", "doc-c"}), "_book_texts": _texts()}
    finding = {**_finding(PAINT), "standard_document_id": "doc-c", "standard_clause": "2.1", "standard_page": 1}
    p = rp.rule_point({**ROW, "standard_reference": "ZZ-1"}, ctx, finding, {}, proof=(True, True))
    assert p["clause"] is None and p["_clause_unconfirmed"] == "2.1"
    ok = rp.rule_point({**ROW, "standard_reference": "ZZ-1"}, ctx, {**finding, "requirement_source_text": HYDRO, "standard_page": 1},
                       {}, proof=(True, True))  # fmt: skip
    assert ok["clause"] == "2.1" and ok["_clause_unconfirmed"] is None
    doubt = rp.rule_point({**ROW, "standard_reference": "ZZ-1"}, ctx, {**finding, "requirement_source_text": COST, "standard_page": 2},
                          {}, proof=(True, True))  # fmt: skip
    assert doubt["clause"] == "2.1" and doubt["_clause_unconfirmed"] is None  # a doubt keeps the clause


def test_every_reader_reads_the_clause_rule_through_read_now():
    (got,) = words.read_now([_line(COST, 2)], [], holds=lambda *_a: False)
    assert got["clause"] == "" and got[words.CLAUSE_UNCONFIRMED_KEY] == "2.1"
    (same,) = words.read_now([_line(COST, 2)], [], holds=lambda *_a: None)
    assert same["clause"] == "2.1"  # code cannot tell: nothing changes
    (unsure,) = words.read_now([_line(COST, 2)], [], holds=lambda *_a: standards.CLAUSE_UNSURE)
    assert unsure["clause"] == "" and unsure[words.CLAUSE_UNCHECKED_KEY] is True


def test_an_ai_point_shows_its_unverified_rule_words_only_where_the_book_holds_them():
    ctx = {"run_id": "r", "paper_document_id": "p", "book_of": {"R-3": ("doc-b", "ZZ-1")}, "readable": frozenset({"p", "doc-b"}),
           "_book_pages": BOOKS}  # fmt: skip

    def line(text):
        return {"item_id": "R-3", "source": "rule", "standard": "ZZ-1", "clause": "4.1", "verdict": "Query", "ai_verdict": "Query",
                "standard_document_id": "doc-b", "requirement": text, "quotes_checked": {"paper": True, "clause": False}}  # fmt: skip

    assert rp.ai_point(line(STORED), ctx)["rule_text"] == standards.book_words("doc-b", STORED, None, BOOKS)
    assert rp.ai_point(line("Widget part reference"), ctx)["rule_text"] is None
