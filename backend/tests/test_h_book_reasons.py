# ruff: noqa: F811
"""Piece H (order 14): the reason a rule book was chosen is stored with the run and served on the results page.

Invented values only. Before this, the run kept only the book ids, so every book's `why` came back empty."""

from __future__ import annotations

import pytest

from app import aim_review, aim_review_store, aim_review_view, db
from app.aim_review import engine as E
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    PAPER,
    MemoryStore,
    open_aim_db,
)
from tests.test_aim_store_runs import (  # noqa: F401 - fixture and helpers
    NOW,
    _line,
    _result,
    _started,
    temp_storage,
)
from tests.test_p3_review_jobs import _doc


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


def _run(aim_db, run_id, store):
    return aim_review.run(
        aim_db,
        run_id=run_id,
        paper_id=PAPER,
        allowed_books=frozenset({BOOK_A, BOOK_B}),
        store=store,
        max_usd=5.0,
        model=E.FakeModel(kind="datasheet", subject_key="test_item"),
    )


def test_a_built_checklist_gives_every_carried_book_its_reason(aim_db):
    r = _run(aim_db, "run_h_1", MemoryStore())
    assert r.books, "the run carried no book: the test has nothing to check"
    assert set(r.book_why) >= set(r.books)
    assert all(r.book_why[b] for b in r.books), r.book_why


def test_a_reused_checklist_gives_the_same_reasons(aim_db):
    store = MemoryStore()
    first = _run(aim_db, "run_h_1", store)
    second = _run(aim_db, "run_h_2", store)
    assert second.checklist_reused is True
    assert {b: second.book_why[b] for b in second.books} == {
        b: first.book_why[b] for b in second.books
    }
    assert all(second.book_why[b] for b in second.books)


def test_the_store_keeps_each_books_reason_and_the_page_serves_it(temp_storage):
    run_id = _started("gen_h")
    conn = db.connect()
    res = _result(
        [_line()],
        books=["doc_inv_book"],
        book_why={"doc_inv_book": "governs the equipment type"},
    )
    aim_review_store.finish_run(conn, run_id, res, NOW)
    assert aim_review_store.run(conn, run_id)["books"] == [
        {"id": "doc_inv_book", "why": "governs the equipment type"}
    ]
    _doc("doc_inv_book", "COMPANY_STANDARD", "invented rule book text")
    view = aim_review_view.build(conn, aim_review_store.run(conn, run_id))
    assert [b["why"] for b in view["books"]] == ["governs the equipment type"]


def test_a_result_without_reasons_stores_the_plain_ids_as_before(temp_storage):
    run_id = _started("gen_h0")
    conn = db.connect()
    aim_review_store.finish_run(conn, run_id, _result([_line()]), NOW)
    assert aim_review_store.run(conn, run_id)["books"] == ["doc_inv_book"]


def test_a_book_the_viewer_may_not_read_is_counted_never_named(temp_storage):
    run_id = _started("gen_h2")
    conn = db.connect()
    res = _result(
        [_line()],
        books=["doc_inv_book", "doc_inv_hidden"],
        book_why={"doc_inv_book": "why one", "doc_inv_hidden": "why two"},
    )
    _doc("doc_inv_book", "COMPANY_STANDARD", "invented rule book text")
    _doc("doc_inv_hidden", "COMPANY_STANDARD", "invented hidden book text")
    aim_review_store.finish_run(conn, run_id, res, NOW)

    class Scope:
        def may_read(self, doc_id):
            return doc_id != "doc_inv_hidden"

    view = aim_review_view.build(conn, aim_review_store.run(conn, run_id), Scope())
    text = str(view["books"])
    assert "why two" not in text and "doc_inv_hidden" not in text
    assert view["books_not_readable"] == 1


def test_a_book_the_scope_step_gave_no_words_for_still_gets_a_reason(aim_db, monkeypatch):
    """Planner 19 Nov, item 1: 15 of 20 books said "the reason was not recorded" on fresh reviews. A book with no scope words is given the
    table's reason (governs, method, cited), else where it came from; never nothing."""
    monkeypatch.setattr(E, "_book_reasons", lambda checklist: {})  # the scope step recorded no words at all
    r = _run(aim_db, "run_h_3", MemoryStore())
    assert r.books, "the run carried no book: the test has nothing to check"
    assert all(str(r.book_why.get(b) or "").strip() for b in r.books), r.book_why
