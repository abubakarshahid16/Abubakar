"""`aim_review.candidates`: plan time, library metadata only. No model call, no socket, no write; a book the caller may not read
is counted, never named; a saved checklist decides by itself; at most 20 books."""

from __future__ import annotations

import pytest

from app import aim_review
from app.aim_review import library as L
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    BOOK_C,
    PAPER,
    MemoryStore,
    open_aim_db,
)


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


ALL = frozenset({PAPER, BOOK_A, BOOK_B, BOOK_C})


@pytest.fixture
def no_model(monkeypatch):
    """Any attempt to reach a model or the Claude socket fails the test."""
    from app import agent_claude, reader_transport

    def refuse(*_a, **_k):
        raise AssertionError("candidates asked a model")

    monkeypatch.setattr(reader_transport, "transport", refuse)
    monkeypatch.setattr(agent_claude, "_request", refuse)
    monkeypatch.setattr(agent_claude, "_send_once", refuse)


@pytest.fixture
def kind_datasheet(monkeypatch):
    from app import agent_review_kind

    monkeypatch.setattr(
        agent_review_kind,
        "read_kind",
        lambda conn, doc: {
            "kind": "datasheet",
            "known": True,
            "method": "title_cue",
            "guess": False,
        },
    )
    monkeypatch.setattr(
        agent_review_kind, "read_equipment", lambda doc, allowed: (None, None)
    )


def _state(conn):
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
    ]
    return [
        (t, conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]) for t in tables
    ]


def test_candidates_lists_the_books_with_rules_of_the_kind(
    aim_db, no_model, kind_datasheet
):
    c = aim_review.candidates(aim_db, PAPER, ALL, MemoryStore())
    assert c.kind == "datasheet" and c.equipment_type is None
    assert {b["id"] for b in c.books} == {BOOK_A, BOOK_B, BOOK_C}
    assert all(b["why"] == L.WHY_RULES for b in c.books)
    assert c.unreadable == 0
    assert PAPER not in {b["id"] for b in c.books}


def test_candidates_makes_no_model_call_and_no_write(aim_db, no_model, kind_datasheet):
    before, changes = _state(aim_db), aim_db.total_changes
    aim_review.candidates(aim_db, PAPER, ALL, MemoryStore())
    assert _state(aim_db) == before and aim_db.total_changes == changes


def test_a_book_the_caller_may_not_read_is_counted_never_named(
    aim_db, no_model, kind_datasheet
):
    c = aim_review.candidates(aim_db, PAPER, frozenset({PAPER, BOOK_A}), MemoryStore())
    assert [b["id"] for b in c.books] == [BOOK_A]
    assert c.unreadable == 2
    text = repr(c)
    assert BOOK_B not in text and BOOK_C not in text
    assert "QX-STD-202" not in text and "QX-STD-303" not in text


def test_a_saved_checklist_decides_the_books(aim_db, no_model, monkeypatch):
    from app import agent_review_kind

    monkeypatch.setattr(
        agent_review_kind,
        "read_kind",
        lambda conn, doc: {
            "kind": "datasheet",
            "known": True,
            "method": "title_cue",
            "guess": False,
        },
    )
    type_id = sorted(L.type_ids())[0]
    monkeypatch.setattr(
        agent_review_kind,
        "read_equipment",
        lambda doc, allowed: (type_id, "classification"),
    )
    store = MemoryStore()
    key = f"datasheet__{type_id}"
    store.put(
        key,
        {
            "built_from": "standards only, no paper",
            "items": [],
            "books": [{"alias": "B01", "book": BOOK_B}],
        },
        run_id="r0",
        usd=0.0,
    )
    c = aim_review.candidates(aim_db, PAPER, ALL, store)
    assert c.checklist_key == key and c.checklist_saved
    assert [(b["id"], b["why"]) for b in c.books] == [(BOOK_B, L.WHY_SAVED)]


def test_an_unknown_kind_offers_no_rules_of_a_kind(aim_db, no_model, monkeypatch):
    from app import agent_review_kind

    monkeypatch.setattr(
        agent_review_kind,
        "read_kind",
        lambda conn, doc: {
            "kind": None,
            "known": False,
            "method": "no_cue",
            "guess": False,
        },
    )
    c = aim_review.candidates(aim_db, PAPER, ALL, MemoryStore())
    assert (
        c.kind is None
        and c.books == []
        and c.checklist_key is None
        and not c.checklist_saved
    )


def test_books_an_earlier_review_wanted_are_listed_first(
    aim_db, no_model, kind_datasheet
):
    c = aim_review.candidates(
        aim_db, PAPER, ALL, MemoryStore(), earlier_unlisted=frozenset({BOOK_C})
    )
    assert c.books[0] == {"id": BOOK_C, "why": L.WHY_LAST}


def test_at_most_twenty_books(aim_db, no_model, kind_datasheet, monkeypatch):
    many = [
        {
            "book": f"doc_many{i:02d}",
            "identifier": f"QX-{i}",
            "committee": "",
            "rules": 1,
            "tagged": 0,
            "subjects": [],
        }
        for i in range(30)
    ]
    monkeypatch.setattr(L, "catalog", lambda by_id, pool, top_subjects=6: many)
    monkeypatch.setattr(L, "role_applies", lambda e, k: True)
    monkeypatch.setattr(
        L,
        "library",
        lambda conn, exclude=frozenset(), within=None: [
            {"id": m["book"]} for m in many
        ],
    )
    allowed = frozenset(m["book"] for m in many)
    c = aim_review.candidates(aim_db, PAPER, allowed, MemoryStore())
    assert len(c.books) == L.MAX_CANDIDATES == 20


def test_a_cited_book_is_found_by_its_identifier(
    aim_db, no_model, kind_datasheet, monkeypatch
):
    from app import standard_ids

    monkeypatch.setattr(
        standard_ids, "cited_standards", lambda text: ["QX-STD-202", "QX-STD-999"]
    )
    c = aim_review.candidates(aim_db, PAPER, ALL, MemoryStore())
    whys = {b["id"]: b["why"] for b in c.books}
    assert whys[BOOK_B] == L.WHY_CITED
    assert {"name": "QX-STD-999", "why": f"{L.WHY_CITED}; not held"} in c.not_held


def test_the_stored_kind_spelling_is_the_methods():
    assert L.method_kind("test_record") == "test record"
    assert L.method_kind("transmittal") == "other"
    assert L.method_kind(None) is None
    assert L.method_kind("datasheet") == "datasheet"
