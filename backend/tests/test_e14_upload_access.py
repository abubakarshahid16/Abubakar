"""Order 14 lane E, review R99: (1) rule 5 on the upload route, (3) the ingest wiring of the suggested kind and role.

(1) A user who may not read a held document re-uploads its bytes with a forged page (`uploaded_from`). The answer is
"awaiting grant", and NOTHING about the held document may change: no kind row, no role suggestion, no upload context.
(3) Ingestion calls `document_kind.after_read_in` once the text is chunked, for the document being read in.
Invented text and a temporary database.
"""

from __future__ import annotations

import io
import json

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import access, db, document_kind, ingest
from app.config import settings
from app.db import connect
from app.main import app

NOW = "2026-11-16T00:00:00Z"
CONTRACT_COVER = 'ACME PLANT PROJECT\nCONTRACT No. ZZ-001\nSCHEDULE "W"\nGeneral Terms\nPage 1 of 9\n1. DEFINITIONS'


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    monkeypatch.setattr(settings, "upload_role_suggestion_enabled", True)
    db.reset_connection()
    db.init_db()
    yield
    access.set_user_resolver(None)
    db.reset_connection()


@pytest.fixture
def two_users(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    with connect() as conn:
        for user_id in ("admin_user", "engineer"):
            conn.execute(
                "INSERT INTO users (id,email,display_name,password_hash,created_at) VALUES (?,?,?,?,?)",
                (user_id, f"{user_id}@example.test", user_id, "hash", NOW),
            )
        for rid, name in (
            ("role_admin", "admin"),
            ("role_civil", "Civil"),
            ("role_mech", "Mechanical"),
        ):
            conn.execute(
                "INSERT INTO roles (id,name,description,created_at,kind) VALUES (?,?,?,?,?)",
                (
                    rid,
                    name,
                    name,
                    NOW,
                    "capability" if name == "admin" else "discipline",
                ),
            )
        conn.execute(
            "INSERT INTO user_roles (user_id,role_id,granted_at) VALUES ('admin_user','role_admin',?)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO user_roles (user_id,role_id,granted_at) VALUES ('engineer','role_civil',?)",
            (NOW,),
        )
    access.set_user_resolver(lambda request: request.headers.get("x-test-user"))


def _pdf(marker: bytes) -> bytes:
    return b"%PDF-1.4\n" + marker * 5000 + b"\n%%EOF\n"


def _upload(client, user, data, disciplines, page=None):
    form = {"disciplines": disciplines}
    if page is not None:
        form["uploaded_from"] = page
    return client.post(
        "/api/documents",
        headers={"x-test-user": user},
        data=form,
        files={"file": ("paper.pdf", io.BytesIO(data), "application/pdf")},
    )


def _kind_row(doc_id):
    row = (
        connect()
        .execute("SELECT * FROM document_kinds WHERE document_id = ?", (doc_id,))
        .fetchone()
    )
    return dict(row) if row else None


def test_a_caller_who_may_not_read_the_held_document_writes_nothing_onto_it(two_users):
    client = TestClient(app)
    data = _pdf(b"z")
    held = _upload(client, "admin_user", data, ["Mechanical"]).json()["document"]["id"]
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?,1,?,?,0)",
            (held, CONTRACT_COVER, len(CONTRACT_COVER)),
        )
    before = _kind_row(held)
    r = _upload(client, "engineer", data, ["Civil"], page="standards")
    assert r.status_code == 200 and r.json()["awaiting_grant"] is True
    assert _kind_row(held) == before, (
        "the kind row of a document the caller may not read changed"
    )
    assert document_kind.upload_context(held) is None, (
        "an upload context was kept for a document the caller may not read"
    )


def test_a_caller_who_may_read_the_held_document_still_records_the_page(two_users):
    """The control: the same duplicate by a reader of the document goes through the hook (the move only narrows)."""
    client = TestClient(app)
    data = _pdf(b"y")
    held = _upload(client, "admin_user", data, ["Mechanical"]).json()["document"]["id"]
    r = _upload(client, "admin_user", data, ["Mechanical"], page="review")
    assert r.json()["duplicate_of"] == held and r.json()["awaiting_grant"] is False
    assert document_kind.upload_context(held) == "review"


def test_ingestion_calls_the_suggestion_hook_for_the_document_read_in(
    monkeypatch, tmp_path
):
    called: list[str] = []
    original = document_kind.after_read_in

    def record(doc_id):
        called.append(doc_id)
        original(doc_id)

    class Stop(Exception):
        pass

    def stop_after_the_hook(_doc_id):
        raise Stop("the test stops ingestion after the chunk stage")

    monkeypatch.setattr(document_kind, "after_read_in", record)
    monkeypatch.setattr(ingest.intake_blocks, "refresh", stop_after_the_hook)
    pdf = pymupdf.open()
    pdf.new_page().insert_text(
        (72, 100), "ACME PLANT PROJECT\nPUMP DATA SHEET\nRated flow 100 m3/h"
    )
    path = tmp_path / "sheet.pdf"
    pdf.save(str(path))
    pdf.close()
    with path.open("rb") as fh:
        doc_id = (
            TestClient(app)
            .post(
                "/api/documents",
                files={"file": ("sheet.pdf", fh, "application/pdf")},
                data={"uploaded_from": "review"},
            )
            .json()["document"]["id"]
        )
    ingest.IngestionWorker().process(doc_id)
    assert called == [doc_id]
    # the hook ran for real: the suggested role is in the kind row's evidence (the router writes none)
    row = _kind_row(doc_id)
    assert row is not None and "role_suggestion" in json.loads(row["evidence"] or "{}")
