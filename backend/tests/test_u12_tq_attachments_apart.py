"""Update 12 (lead-4, planner note 26 Nov 2026 15:15, item 2): a technical-query attachment nobody filed into the library is never a rule
book, never review or Chat evidence, never in search, and never counted among the library's documents: the dashboard and the kind counts
leave it out and say "N technical-query attachments" apart. Filing it with a role ends that. Invented files only; the live database is
never touched."""

from __future__ import annotations

import pytest

from app import access, db, fts_index, metrics, search
from app import technical_queries as tq
from app.aim_review import library as L
from app.config import settings

STD, ATT, ATT_ISO = "doc_std_held", "doc_att_plain", "doc_att_isoname"
NOW = "2026-11-26T00:00:00Z"


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "u12.sqlite")
    monkeypatch.setattr(settings, "technical_queries_enabled", True)
    db.reset_connection()
    db.init_db()
    fts_index.ensure_schema()
    tq.ensure_schema()
    with db.connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for doc, name, chunks in (
            (STD, "invented-held-standard.pdf", 7),
            (ATT, "invented-attachment.pdf", 3),
            (ATT_ISO, "ISO 99999-1.pdf", 4),
        ):
            conn.execute(
                "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path, page_count, status, uploaded_at, chunk_count, chunk_count_total)"
                " VALUES (?, ?, ?, 1, ?, 2, 'ready', ?, ?, ?)",
                (doc, name, doc.ljust(64, "0"), f"/nowhere/{doc}", NOW, chunks, chunks),
            )
        conn.execute(
            "INSERT INTO document_classification (document_id, document_role, suggested_by) VALUES (?, 'COMPANY_STANDARD', 'none')",
            (STD,),
        )
        for i, doc in enumerate((ATT, ATT_ISO)):
            conn.execute(
                "INSERT INTO query_attachments (id, message_id, filename, media_type, size_bytes, document_id, created_at)"
                " VALUES (?, 'msg_invented', 'f.pdf', 'application/pdf', 1, ?, ?)",
                (f"att{i}", doc, NOW),
            )
    yield
    db.reset_connection()


def _file(doc: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE query_attachments SET filed_at = ?, filed_by = 'u1' WHERE document_id = ?",
            (NOW, doc),
        )


def test_an_unfiled_attachment_is_in_no_scope_and_only_the_technical_query_screens_hold_it(
    lib,
):
    s = access.unrestricted_scope()
    assert STD in s.allowed_document_ids and not {ATT, ATT_ISO} & s.allowed_document_ids
    assert (
        s.query_attachment_ids == {ATT, ATT_ISO}
        and s.may_read_attachment(ATT)
        and not s.may_read(ATT)
    )


def test_the_every_document_stand_in_leaves_it_out(lib):
    assert search.every_document_id() == {STD}


def test_it_is_never_a_rule_book_even_named_like_a_public_standard_and_even_if_a_caller_passes_its_id(
    lib,
):
    assert L.is_public_name(
        "ISO 99999-1"
    )  # the name alone would make it a usable public book
    with db.connect() as conn:
        assert [e["id"] for e in L.library(conn)] == [STD]
        assert L.library(conn, within=frozenset({STD, ATT, ATT_ISO})) == [
            e for e in L.library(conn) if e["id"] == STD
        ]
    _file(
        ATT_ISO
    )  # filed on purpose: from then on it is a library document like any other
    with db.connect() as conn:
        assert {e["id"] for e in L.library(conn)} == {STD, ATT_ISO}


def test_the_dashboard_counts_the_library_without_it_and_says_how_many_are_apart(lib):
    got = metrics.corpus(None)  # corpus-wide: an admin, or sign-in off
    assert (got["documents"], got["chunks_retrievable"]) == (1, 7)
    assert (
        got["technical_query_attachments"],
        got["technical_query_attachment_passages"],
    ) == (2, 7)
    scoped = metrics.corpus(sorted(access.unrestricted_scope().allowed_document_ids))
    assert scoped["documents"] == 1 and scoped["technical_query_attachments"] is None
    _file(ATT)
    got = metrics.corpus(None)
    assert (got["documents"], got["technical_query_attachments"]) == (2, 1)


def test_a_failed_attachment_never_names_its_file_on_the_dashboard(lib):
    with db.connect() as conn:
        conn.execute(
            "UPDATE documents SET status = 'failed', error_message = 'invented' WHERE id = ?",
            (ATT,),
        )
    assert ATT not in {f["id"] for f in metrics.jobs(None)["failures"]}


def test_the_kind_counts_leave_it_out_with_sign_in_off(lib):
    from fastapi.testclient import TestClient

    from app.main import app

    seen: dict = {}

    def counts(allowed):
        seen["allowed"] = allowed
        return {}

    import app.doc_router as router

    monkey = pytest.MonkeyPatch()
    monkey.setattr(router, "counts", counts)
    try:
        assert TestClient(app).get("/api/document-kinds").status_code == 200
    finally:
        monkey.undo()
    assert seen["allowed"] is not None and not {ATT, ATT_ISO} & set(seen["allowed"])


def test_with_no_attachment_table_nothing_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "plain.sqlite")
    db.reset_connection()
    db.init_db()
    fts_index.ensure_schema()
    try:
        assert (
            metrics._where(None, "id") == ("", [])
            and metrics.attachments_apart() == frozenset()
        )
        assert metrics.corpus(None)["technical_query_attachments"] == 0
    finally:
        db.reset_connection()
