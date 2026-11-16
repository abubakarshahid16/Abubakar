"""Order 14, lane A (for lanes D and the gates G1, G7): a checklist line of the calculator shows the HELD clause's own stored text
as its quote, found by code in the book's pages, never our checklist wording; a book the library does not hold is named "book
missing", with no clause, no rule words and never a Pass or Fail. Invented books and texts only."""

from __future__ import annotations

import sqlite3

from app import agent_review_calculator as calc
from app.agent_review_checklist_books import ChecklistBooks

CLAUSE_TEXT = "The estimated inlet piping pressure drop shall be stated on the relief valve specification sheet."


class FakeBooks:
    def __init__(self, answers):
        self.answers = answers

    def cite(self, standard, clause):
        return self.answers.get((standard, clause), {})


def _result(standard, clause, status="NON_COMPLIANT"):
    return {"rule_id": "PSV-24", "status": status, "fact_id": "f1", "value": "12 barg", "page": 2, "field": "Set pressure",
            "text": "Our own words for the check.", "detail": "Set pressure 12 barg (page 2) is above the limit.",
            "standard": standard, "clause": clause}  # fmt: skip


PAGES = {2: "Set pressure 12 barg"}


def test_a_held_clause_is_quoted_from_the_book_and_our_words_are_kept_apart():
    books = FakeBooks(
        {("BOOK-1", "9.7.2"): {"book_id": "d1", "quote": CLAUSE_TEXT, "page": 22}}
    )
    line = calc.checklist_lines(
        [_result("BOOK-1", "9.7.2")], page_texts=PAGES, books=books
    )[0]
    assert (
        line["clause_quote"] == CLAUSE_TEXT
        and line["clause_page"] == 22
        and line["quotes_checked"]["clause"] is True
    )
    assert line["check_words"] == "Our own words for the check."
    assert (
        line["verdict"] == calc.FAIL
    )  # a held clause with its own text keeps the code's decision


def test_a_held_book_without_a_found_clause_text_shows_no_quote():
    books = FakeBooks({("BOOK-1", "9.9"): {"book_id": "d1"}})
    line = calc.checklist_lines(
        [_result("BOOK-1", "9.9")], page_texts=PAGES, books=books
    )[0]
    assert line["clause_quote"] == "" and line["quotes_checked"]["clause"] is False
    assert line["check_words"] == "Our own words for the check."


def test_a_book_not_held_is_book_missing_with_no_clause_no_words_and_no_verdict():
    books = FakeBooks({("BOOK-X annex", "A.1"): {"missing": "BOOK-X annex"}})
    for status in ("NON_COMPLIANT", "COMPLIANT"):
        line = calc.checklist_lines(
            [_result("BOOK-X annex", "A.1", status)], page_texts=PAGES, books=books
        )[0]
        assert (
            line["standard"] == "book missing: BOOK-X annex"
            and line["clause"] == ""
            and line["clause_quote"] == ""
        )
        assert line["verdict"] == calc.QUERY and "not held" in line["why"]


def test_without_a_book_lookup_the_line_is_as_before():
    line = calc.checklist_lines([_result("BOOK-1", "9.7.2")], page_texts=PAGES)[0]
    assert (
        line["clause_quote"] == "Our own words for the check."
        and "check_words" not in line
    )


def _db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE documents (id TEXT, filename TEXT);
        CREATE TABLE standard_requirements (id INTEGER, standard_document_id TEXT, clause TEXT, page INTEGER,
                                            source_text TEXT, superseded_at TEXT);
        CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);
        """
    )
    conn.execute("INSERT INTO documents VALUES ('d1', 'SAES-J-600.pdf')")
    conn.execute(
        "INSERT INTO standard_requirements VALUES (1, 'd1', '9.7.2', 22, 'A text the reader made up, not on the page.', NULL)"
    )
    conn.execute(
        "INSERT INTO standard_requirements VALUES (2, 'd1', '9.7.2', 22, ?, NULL)",
        (CLAUSE_TEXT,),
    )
    conn.execute(
        "INSERT INTO pages VALUES ('d1', 22, ?)",
        ("9.7.2 Inlet Piping Pressure Drop\n" + CLAUSE_TEXT,),
    )
    return conn


def test_the_lookup_quotes_only_a_stored_text_found_in_the_books_pages():
    books = ChecklistBooks(_db())
    got = books.cite("SAES-J-600", "9.7.2")
    assert got == {
        "book_id": "d1",
        "quote": CLAUSE_TEXT,
        "page": 22,
    }  # the unfound text of row 1 is skipped
    assert books.cite("SAES-J-600", "4.4") == {"book_id": "d1"}
    assert books.cite("API 610 datasheet annex", "A.1") == {
        "missing": "API 610 datasheet annex"
    }
    assert books.cite("", "1") == {}
