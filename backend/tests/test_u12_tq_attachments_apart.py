"""Update 12 (lead-4, planner note 26 Nov 2026 15:15, item 2): a technical-query attachment nobody filed into the library (a PDF or a
Word file) is never a rule book, never review or Chat evidence, never in search, and never counted among the library's documents: the
dashboard and the kind counts leave it out and say "N technical-query attachments" apart. Its own access grant never widens access (rule 5:
a filter only narrows): a person whose only grant is that attachment reads it on the technical-query screens and nowhere else. Filing it
with a role ends that. Invented files only; the live database is never touched."""

from __future__ import annotations

import pytest

from app import access, db, fts_index, metrics, search
from app import technical_queries as tq
from app.aim_review import library as L
from app.config import settings

STD, ATT, ATT_ISO, ATT_DOCX = (
    "doc_std_held",
    "doc_att_plain",
    "doc_att_isoname",
    "doc_att_word",
)
ATTACHMENTS = {ATT, ATT_ISO, ATT_DOCX}
NOW = "2026-11-26T00:00:00Z"
WORD = "zqxvordium"  # an invented word every invented document holds, so a keyword search would find each of them


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
            (ATT_DOCX, "invented-attachment-letter.docx", 2),
        ):
            conn.execute(
                "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path, page_count, status, uploaded_at, chunk_count, chunk_count_total)"
                " VALUES (?, ?, ?, 1, ?, 2, 'ready', ?, ?, ?)",
                (doc, name, doc.ljust(64, "0"), f"/nowhere/{doc}", NOW, chunks, chunks),
            )
            conn.execute(
                "INSERT INTO chunks (id, document_id, filename, ordinal, page_start, page_end, text, token_count, content_hash)"
                " VALUES (?, ?, ?, 1, 1, 1, ?, 6, ?)",
                (
                    f"ch_{doc}",
                    doc,
                    name,
                    f"Invented passage about the {WORD} test fitting.",
                    f"h_{doc}",
                ),
            )
        conn.execute(
            "INSERT INTO document_classification (document_id, document_role, suggested_by) VALUES (?, 'COMPANY_STANDARD', 'none')",
            (STD,),
        )
        for i, (doc, fname, media) in enumerate(
            (
                (ATT, "f.pdf", "application/pdf"),
                (ATT_ISO, "g.pdf", "application/pdf"),
                (
                    ATT_DOCX,
                    "h.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            )
        ):
            conn.execute(
                "INSERT INTO query_attachments (id, message_id, filename, media_type, size_bytes, document_id, created_at)"
                " VALUES (?, 'msg_invented', ?, ?, 1, ?, ?)",
                (f"att{i}", fname, media, doc, NOW),
            )
        # a person whose ONLY grant is the attachments (the grant the import wrote), and one who may also read the held standard
        conn.execute(
            "INSERT INTO users(id,email,display_name,password_hash,created_at) VALUES ('u_att','a@example.test','A','x',?)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO users(id,email,display_name,password_hash,created_at) VALUES ('u_lib','b@example.test','B','x',?)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO roles(id, name, description, kind, created_at) VALUES ('r_att', 'invented-att-role', 'x', 'discipline', ?)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO roles(id, name, description, kind, created_at) VALUES ('r_lib', 'invented-lib-role', 'x', 'discipline', ?)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO user_roles(user_id, role_id, granted_at) VALUES ('u_att', 'r_att', ?)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO user_roles(user_id, role_id, granted_at) VALUES ('u_lib', 'r_lib', ?)",
            (NOW,),
        )
        for doc in ATTACHMENTS:
            conn.execute(
                "INSERT INTO document_role_access(document_id, role_id, granted_at) VALUES (?, 'r_att', ?)",
                (doc, NOW),
            )
        for doc in (STD, *ATTACHMENTS):
            conn.execute(
                "INSERT INTO document_role_access(document_id, role_id, granted_at) VALUES (?, 'r_lib', ?)",
                (doc, NOW),
            )
    for doc in (STD, *ATTACHMENTS):
        fts_index.index_document(
            doc
        )  # the keyword index holds every one of them, attachments included
    yield
    db.reset_connection()


def _file(doc: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE query_attachments SET filed_at = ?, filed_by = 'u1' WHERE document_id = ?",
            (NOW, doc),
        )


def test_an_unfiled_attachment_pdf_or_word_is_in_no_scope_and_only_the_technical_query_screens_hold_it(
    lib,
):
    s = access.unrestricted_scope()
    assert STD in s.allowed_document_ids and not ATTACHMENTS & s.allowed_document_ids
    assert (
        s.query_attachment_ids == ATTACHMENTS
        and s.may_read_attachment(ATT_DOCX)
        and not s.may_read(ATT_DOCX)
    )


def test_its_own_grant_never_widens_access_rule_5(lib):
    only = access.scope_for_user(
        "u_att"
    )  # every grant this person holds is an attachment's
    assert (
        only.allowed_document_ids == frozenset()
        and only.query_attachment_ids == ATTACHMENTS
    )
    assert not any(only.may_read(d) for d in ATTACHMENTS) and all(
        only.may_read_attachment(d) for d in ATTACHMENTS
    )
    both = access.scope_for_user("u_lib")
    assert (
        both.allowed_document_ids == {STD} and both.query_attachment_ids == ATTACHMENTS
    )


def test_a_search_with_any_persons_scope_never_finds_it_though_the_index_holds_it(lib):
    def docs(allowed):
        return {
            h["document_id"]
            for h in fts_index.search(WORD, allowed_document_ids=frozenset(allowed))
        }

    assert docs({STD, *ATTACHMENTS}) == {
        STD,
        *ATTACHMENTS,
    }  # the control: the index finds every one when they are passed in
    assert docs(access.scope_for_user("u_att").allowed_document_ids) == set()
    assert docs(access.scope_for_user("u_lib").allowed_document_ids) == {STD}
    assert docs(access.unrestricted_scope().allowed_document_ids) == {STD}
    assert docs(search.every_document_id()) == {STD}


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
        assert L.library(conn, within=frozenset({STD, *ATTACHMENTS})) == [
            e for e in L.library(conn) if e["id"] == STD
        ]
    _file(
        ATT_ISO
    )  # filed on purpose: from then on it is a library document like any other
    with db.connect() as conn:
        assert {e["id"] for e in L.library(conn)} == {STD, ATT_ISO}


def test_the_dashboard_counts_the_library_without_them_and_says_how_many_are_apart(lib):
    got = metrics.corpus(None)  # corpus-wide: an admin, or sign-in off
    assert (got["documents"], got["chunks_retrievable"]) == (1, 7)
    assert (
        got["technical_query_attachments"],
        got["technical_query_attachment_passages"],
    ) == (3, 9)
    scoped = metrics.corpus(sorted(access.unrestricted_scope().allowed_document_ids))
    assert scoped["documents"] == 1 and scoped["technical_query_attachments"] is None
    _file(ATT_DOCX)
    got = metrics.corpus(None)
    assert (got["documents"], got["technical_query_attachments"]) == (2, 2)


def test_a_failed_attachment_never_names_its_file_on_the_dashboard(lib):
    with db.connect() as conn:
        conn.execute(
            "UPDATE documents SET status = 'failed', error_message = 'invented' WHERE id = ?",
            (ATT_DOCX,),
        )
    assert ATT_DOCX not in {f["id"] for f in metrics.jobs(None)["failures"]}


def test_the_kind_counts_leave_them_out_with_sign_in_off(lib):
    from fastapi.testclient import TestClient

    import app.doc_router as router
    from app.main import app

    seen: dict = {}

    def counts(allowed):
        seen["allowed"] = allowed
        return {}

    monkey = pytest.MonkeyPatch()
    monkey.setattr(router, "counts", counts)
    try:
        assert TestClient(app).get("/api/document-kinds").status_code == 200
    finally:
        monkey.undo()
    assert seen["allowed"] is not None and not ATTACHMENTS & set(seen["allowed"])


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
