"""#772 (R8): a standard cited by the standards a review used, and not held by the library, is
LISTED in the Review notes, never silently ignored. Invented standards and text only."""

from __future__ import annotations

import pytest

from app import db, standard_references, submittal_review
from app.config import settings
from app.db import connect
from tests.test_review_screen import world  # noqa: F401 - fixture

ALL = frozenset()


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def _standard(doc_id, filename, text=None, *, number=None, superseded=False):
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,uploaded_at)"
            " VALUES (?, ?, ?, 1, '/nowhere', 'ready', '2026-01-01')",
            (doc_id, filename, f"sha-{doc_id}"),
        )
        conn.execute(
            "INSERT INTO document_classification (document_id, document_role, document_number,"
            " superseded_by, suggested_by) VALUES (?, 'COMPANY_STANDARD', ?, ?, 'human')",
            (doc_id, number, "other" if superseded else None),
        )
        if text is not None:
            conn.execute(
                "INSERT INTO chunks (id, document_id, filename, ordinal, page_start, page_end,"
                " text, token_count, content_hash) VALUES (?, ?, ?, 0, 1, 1, ?, 9, ?)",
                (f"{doc_id}-0", doc_id, filename, text, f"h-{doc_id}"),
            )


def _allowed():
    return frozenset(r["id"] for r in connect().execute("SELECT id FROM documents"))


def test_a_cited_standard_the_library_does_not_hold_is_listed():
    _standard("a", "Spec A.pdf", "Valves shall comply with API 526 and with ISO 15156.")
    _standard(
        "b", "API 526.pdf", "Flanged steel pressure relief valves.", number="API 526"
    )
    missing, unread, used = standard_references.not_held(["a"], _allowed())
    assert [m["identifier"] for m in missing] == ["ISO 15156"]
    assert missing[0]["cited_by"] == 1
    assert (unread, used) == (0, 1)


def test_a_held_standard_is_not_listed_and_nothing_is_said_when_all_are_held():
    _standard("a", "Spec A.pdf", "Valves shall comply with API 526.")
    _standard(
        "b", "API 526.pdf", "Flanged steel pressure relief valves.", number="API 526"
    )
    assert (
        standard_references.notes(*standard_references.not_held(["a"], _allowed()))
        == []
    )


def test_a_superseded_copy_is_still_a_held_copy():
    _standard("a", "Spec A.pdf", "Valves shall comply with API 526.")
    _standard("b", "API 526.pdf", "Old edition.", number="API 526", superseded=True)
    assert standard_references.not_held(["a"], _allowed())[0] == []


def test_a_standard_does_not_cite_itself():
    _standard("a", "API 526.pdf", "This API 526 covers valves.", number="API 526")
    assert standard_references.not_held(["a"], _allowed())[0] == []


def test_two_standards_citing_the_same_missing_one_count_it_once_with_two_citers():
    _standard("a", "Spec A.pdf", "See ISO 15156.")
    _standard("b", "Spec B.pdf", "Also ISO 15156.")
    missing, _unread, used = standard_references.not_held(["a", "b"], _allowed())
    assert [(m["identifier"], m["cited_by"]) for m in missing] == [("ISO 15156", 2)]
    assert used == 2


def test_a_standard_with_no_text_is_counted_as_not_read_never_as_citing_nothing():
    _standard("a", "Spec A.pdf", None)
    _standard("b", "Spec B.pdf", "See ISO 15156.")
    missing, unread, used = standard_references.not_held(["a", "b"], _allowed())
    assert (unread, used) == (1, 2)
    note = standard_references.notes(missing, unread, used)[0]
    assert "1 of the 2 standards had no readable text" in note["detail"]


def test_a_standard_the_caller_may_not_read_is_neither_read_nor_held():
    _standard("a", "Spec A.pdf", "See ISO 15156 and API 526.")
    _standard("b", "API 526.pdf", "Valves.", number="API 526")
    missing, _u, _n = standard_references.not_held(["a"], frozenset({"a"}))
    assert sorted(m["identifier"] for m in missing) == ["API 526", "ISO 15156"]


def test_the_note_lists_a_bounded_number_and_counts_the_rest():
    text = " ".join(f"ISO {15000 + i}" for i in range(20))
    _standard("a", "Spec A.pdf", text)
    note = standard_references.notes(*standard_references.not_held(["a"], _allowed()))[
        0
    ]
    assert note["count"] == 20
    assert "and 5 more" in note["detail"]
    assert note["detail"].count("(cited by 1)") == standard_references.LISTED


def test_for_run_reads_the_standards_the_run_used():
    submittal_review.ensure_schema()
    _standard("a", "Spec A.pdf", "See ISO 15156.")
    _standard("z", "Spec Z.pdf", "See ISO 9999.")
    with connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at)"
            " VALUES ('r1', 'a', 'completed', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO review_applicable_standards (id, review_run_id, standard_document_id,"
            " included, created_at) VALUES ('x1', 'r1', 'a', 1, '2026-01-01')"
        )
    notes = standard_references.for_run("r1", _allowed())
    assert len(notes) == 1 and "ISO 15156" in notes[0]["detail"]
    assert "ISO 9999" not in notes[0]["detail"], (
        "a standard the run did not use is not read"
    )


def test_a_check_that_cannot_run_is_said_with_the_error_type_only(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("SECRET-TEXT")

    submittal_review.ensure_schema()
    monkeypatch.setattr(standard_references, "not_held", boom)
    notes = standard_references.for_run("r1", ALL)
    assert "could not run (RuntimeError)" in notes[0]["detail"]
    assert "SECRET-TEXT" not in str(notes)


def test_the_crs_content_carries_the_note(world):  # noqa: F811
    """Wiring: the real `_crs_content` of a real run puts the note in the Review notes."""
    from app import access, main

    _sub, run, scope = world
    used = (
        connect()
        .execute(
            "SELECT standard_document_id AS d FROM review_applicable_standards"
            " WHERE review_run_id = ? AND COALESCE(included, 1) = 1",
            (run,),
        )
        .fetchone()["d"]
    )
    with connect() as conn:
        conn.execute(
            "INSERT INTO chunks (id, document_id, filename, ordinal, page_start, page_end, text,"
            " token_count, content_hash) VALUES ('ref-chunk', ?, 'x.pdf', 999, 1, 1, ?, 9, 'h-ref')",
            (used, "Bearings shall follow ISO 15156."),
        )
    _rows, meta, *_ = main._crs_content(
        run, access.AccessScope(user_id=None, allowed_document_ids=scope)
    )
    mine = [n for n in meta["review_notes"] if n["note"] == standard_references.NOTE]
    assert len(mine) == 1 and "ISO 15156" in mine[0]["detail"]


def test_standards_that_could_not_be_read_are_said_even_when_nothing_else_is_missing():
    _standard("a", "Spec A.pdf", None)
    notes = standard_references.notes(*standard_references.not_held(["a"], _allowed()))
    assert len(notes) == 1 and "1 of the 1 standards used" in notes[0]["detail"]
    assert "not checked against the library" in notes[0]["detail"]
    _standard("b", "Spec B.pdf", "Plain text with no citation.")
    assert (
        standard_references.notes(*standard_references.not_held(["b"], _allowed()))
        == []
    )
