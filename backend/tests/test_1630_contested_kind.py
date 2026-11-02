"""#1630: a kind that is only a guess with a conflict does not close the body path.

The number says one kind and the title another. It keeps its procedure path and its
clause review: its own text is still checked. The documents here are invented.
"""

from __future__ import annotations

import json

import pytest

from app import clause_review, db, document_kind, procedure_text
from tools import crs_bench
from app.config import settings

DATASHEET_COVER = {
    "page_no": 1,
    "text": "MECHANICAL DATASHEET\nDRUM\nDOC NO: SITE-2003-SP-0001\nRev. 00\n",
}
PROCEDURE_COVER = {
    "page_no": 1,
    "text": "OPERATING PROCEDURE\nDOC NO: SITE-2003-SP-0001\nRev. 00\n",
}


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "kinds.sqlite")
    monkeypatch.setattr(settings, "document_kind_enabled", True)
    monkeypatch.setattr(settings, "procedure_path_enabled", True)
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def _doc(doc_id, kind="specification", state="suggested", evidence=None):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,'2026-11-02')",
            (doc_id, doc_id + ".pdf", "sha-" + doc_id, doc_id + ".pdf"),
        )
        conn.execute(
            "INSERT INTO document_kinds (document_id,kind,state,evidence,routed_at)"
            " VALUES (?,?,?,?,'2026-11-02')",
            (doc_id, kind, state, json.dumps(evidence or {})),
        )


CONFLICT = {"guess": True, "conflict": "datasheet"}


def test_a_conflict_with_a_datasheet_title_leaves_the_body_open(monkeypatch):
    _doc("d", evidence=CONFLICT)
    assert document_kind.body_equipment_allowed(
        [DATASHEET_COVER], "d", "CONTRACTOR_SUBMITTAL"
    )


def test_a_conflict_between_two_other_kinds_keeps_the_body_shut():
    _doc("d", evidence={"guess": True, "conflict": "procedure"})
    assert not document_kind.body_equipment_allowed(
        [PROCEDURE_COVER], "d", "CONTRACTOR_SUBMITTAL"
    )


def test_a_guess_with_a_conflict_is_contested_until_confirmed():
    _doc("a", evidence=CONFLICT)
    _doc("b", state="confirmed", evidence=CONFLICT)
    _doc("c", evidence={"guess": True})
    _doc("e")
    assert document_kind.contested("a")
    assert not document_kind.contested("b")
    assert not document_kind.contested("c")
    assert not document_kind.contested("e")


def test_the_body_guess_is_marked_on_a_contested_kind_and_the_kind_is_kept():
    _doc("a", evidence=CONFLICT)
    document_kind.mark_equipment_guessed_from_body("a")
    row = (
        db.connect()
        .execute(
            "SELECT kind, state, evidence FROM document_kinds WHERE document_id = 'a'"
        )
        .fetchone()
    )
    assert (row["kind"], row["state"]) == ("specification", "suggested")
    assert json.loads(row["evidence"])["equipment_guessed_from_body"] is True


def test_a_contested_kind_keeps_its_procedure_path_and_clause_review():
    _doc("a", evidence=CONFLICT)
    assert procedure_text.is_procedure_submittal("a")
    assert clause_review.eligible("a")[0] == "specification"


def test_the_bench_kind_is_the_one_the_review_acts_on(monkeypatch):
    _doc("a")
    _doc("b", state="needs_engineer")
    conn = db.connect()
    assert crs_bench.effective_kind(conn, "a", "specification") == "specification"
    assert crs_bench.effective_kind(conn, "b", "specification") == "datasheet"
    assert crs_bench.effective_kind(conn, "a", "drawing") == "drawing"
    monkeypatch.setattr(settings, "procedure_path_enabled", False)
    assert crs_bench.effective_kind(conn, "a", "specification") == "datasheet"
