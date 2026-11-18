# ruff: noqa: F811
"""Piece H (order 14, rule 5): a rule book's reason is a model's free text and can name ANOTHER book. A viewer who may not read that
book never learns its name from it, on the page or in the Excel Summary; a missing reason says the same words in both; the page and
the file say how many of the documents listed before the start were used (hidden books counted, never named). Invented values."""

from __future__ import annotations

import json

import pytest

from app import aim_review_book_why as W
from app import db, review_shown
from tests.test_aim_sheet_rule import (
    BOOK,
    HIDDEN_BOOK,
    NOW,
    PAPER,
    _doc,
    _sheet,
    client,
    make_run,
)
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture

OTHER = "doc_inv_other"


@pytest.fixture
def world(temp_db):
    _doc(PAPER, "invented-paper.pdf")
    _doc(BOOK, "invented-book.pdf")
    _doc(HIDDEN_BOOK, "invented-secret.pdf")
    _doc(OTHER, "invented-other.pdf")


def _page(*allowed):
    r = client(*allowed).get(f"/api/reviews/papers/{PAPER}/general")
    assert r.status_code == 200, r.text
    return r.json()


def _summary_text(*allowed) -> str:
    wb = _sheet(client(*allowed).get(f"/api/reviews/papers/{PAPER}/general/sheet"))
    return "\n".join(
        str(c) for row in wb["Summary"].iter_rows(values_only=True) for c in row if c
    )


def _books(*pairs):
    return [{"id": i, "why": w} for i, w in pairs]


def test_a_reason_naming_a_hidden_book_is_not_served_on_the_page_or_in_the_file(world):
    make_run(
        books=_books(
            (BOOK, "complements invented-secret.pdf for the same service"),
            (HIDDEN_BOOK, "the secret book's own reason"),
        )
    )
    page = _page(PAPER, BOOK)
    assert [b["why"] for b in page["books"]] == [W.WHY_HIDDEN]
    text = json.dumps(page) + _summary_text(PAPER, BOOK)
    assert "invented-secret" not in text and "doc_inv_secret" not in text
    assert "secret book's own reason" not in text
    assert W.WHY_HIDDEN in _summary_text(PAPER, BOOK)


def test_the_name_is_caught_however_it_is_written(world):
    make_run(
        books=_books(
            (BOOK, "Invented  SECRET, see also"),
            (OTHER, "next to the INVENTED_SECRET.PDF book"),
            (HIDDEN_BOOK, "the hidden book is part of the run"),
        )
    )
    reasons = [b["why"] for b in _page(PAPER, BOOK, OTHER)["books"]]
    assert reasons == [W.WHY_HIDDEN, W.WHY_HIDDEN]


def test_a_reason_naming_only_readable_books_is_served_as_written(world):
    make_run(
        books=_books(
            (BOOK, "governs the equipment type; pairs with invented-other"),
            (OTHER, "cited by the paper"),
        )
    )
    page = _page(PAPER, BOOK, OTHER)
    assert [b["why"] for b in page["books"]] == [
        "governs the equipment type; pairs with invented-other",
        "cited by the paper",
    ]


def test_a_viewer_who_may_read_every_book_sees_the_reason_unscrubbed(world):
    make_run(
        books=_books(
            (BOOK, "complements invented-secret.pdf"), (HIDDEN_BOOK, "own reason")
        )
    )
    page = _page(PAPER, BOOK, HIDDEN_BOOK)
    assert [b["why"] for b in page["books"]] == [
        "complements invented-secret.pdf",
        "own reason",
    ]


def test_a_missing_reason_says_the_same_words_on_the_page_and_in_the_file(world):
    make_run(
        books=[BOOK, _books((OTHER, ""))[0]]
    )  # a bare id (an older run) and an empty reason
    page = _page(PAPER, BOOK, OTHER)
    assert [b["why"] for b in page["books"]] == [W.WHY_NOT_RECORDED] * 2
    assert W.WHY_NOT_RECORDED in _summary_text(PAPER, BOOK, OTHER)


def test_a_catalog_alias_or_identifier_of_a_hidden_book_is_caught(world, monkeypatch):
    monkeypatch.setattr(
        W,
        "_catalog_entries",
        lambda conn, run: [
            {"book": HIDDEN_BOOK, "alias": "B03", "identifier": "QX-99-Z"}
        ],
    )
    make_run(
        books=_books(
            (BOOK, "as B03 says"), (OTHER, "see qx 99 z"), (PAPER, "B13 is another")
        )
    )
    got = {b["id"]: b["why"] for b in _page(PAPER, BOOK, OTHER, PAPER)["books"]}
    assert got[BOOK] == W.WHY_HIDDEN and got[OTHER] == W.WHY_HIDDEN
    assert got[PAPER] == "B13 is another"  # B13 is not the hidden book's alias


def test_the_page_and_the_file_say_how_many_listed_documents_were_used(world):
    make_run(books=_books((BOOK, "a"), (HIDDEN_BOOK, "b")))
    with db.connect() as conn:
        review_shown.record_in(
            conn, "gen_run_1", [PAPER, BOOK, HIDDEN_BOOK, OTHER], NOW
        )
    page = _page(PAPER, BOOK)
    assert (
        page["documents_listed"]["listed"] == 3
        and page["documents_listed"]["used"] == 2
    )
    sentence = page["documents_listed"]["sentence"]
    assert sentence == "Of the 3 other documents listed before the start, 2 were used."
    assert sentence in _summary_text(PAPER, BOOK)
    assert "invented-secret" not in json.dumps(
        page
    )  # the hidden book is counted, never named


def test_an_older_run_with_no_stored_list_says_nothing_about_it(world):
    make_run(books=_books((BOOK, "a")))
    assert _page(PAPER, BOOK)["documents_listed"] is None


def test_a_listed_but_not_chosen_book_the_viewer_may_not_read_is_caught_by_its_identifier(
    world,
):
    """The hidden book is only on the list shown before the start (not among the books the run carried), and its file name says
    nothing: its library identifier (the document number) is still never served from another book's reason."""
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO document_classification (document_id, document_role, document_number, suggested_by)"
            " VALUES (?, 'COMPANY_STANDARD', 'QX-77-Z', 'test')",
            (HIDDEN_BOOK,),
        )
        review_shown.record_in(conn, "gen_run_1", [PAPER, BOOK, HIDDEN_BOOK], NOW)
    make_run(books=_books((BOOK, "pairs with qx 77 z for the same service")))
    page = _page(PAPER, BOOK)
    assert [b["why"] for b in page["books"]] == [W.WHY_HIDDEN]
    assert "77" not in json.dumps(page["books"]) and "doc_inv_secret" not in json.dumps(
        page
    )
    assert "QX" not in _summary_text(PAPER, BOOK).upper().replace("WHY_", "")
