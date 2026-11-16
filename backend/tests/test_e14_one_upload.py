"""Order 14 lane E, one upload for the whole app: a SUGGESTED kind and role (never a role), behind one switch, off = byte-same.
Invented covers; a temporary database."""

from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient

from app import claude_approved, db, doc_router, document_kind
from app.config import settings
from app.main import app
from tests.test_upload import pdf_bytes, temp_storage  # noqa: F401 - autouse fixture

CONTRACT_COVER = 'ACME PLANT PROJECT\nCONTRACT No. ZZ-001\nSCHEDULE "W"\nGeneral Terms\nPage 1 of 9\n1. DEFINITIONS'
DATASHEET_COVER = "ACME PLANT PROJECT\nPUMP DATA SHEET\n1 Rated flow 100 m3/h"


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "upload_role_suggestion_enabled", True)


def _doc(doc_id, text, role=None, kind=None, state=None):
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path, status, uploaded_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (doc_id, f"{doc_id}.pdf", f"{doc_id}-sha", 1, "x", "ready", "2026-11-01"),
        )
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?,1,?,?,0)",
            (doc_id, text, len(text)),
        )
        if role:
            conn.execute(
                "INSERT INTO document_classification (document_id, suggested_by, document_role) VALUES (?,?,?)",
                (doc_id, "t", role),
            )
        if state:
            conn.execute(
                "INSERT INTO document_kinds (document_id, kind, state, evidence, router_version, routed_at)"
                " VALUES (?,?,?,?,?,?)",
                (doc_id, kind, state, json.dumps({"cue": "router"}), "1", "2026-11-01"),
            )


def _evidence(doc_id):
    row = (
        db.connect()
        .execute(
            "SELECT kind, state, evidence FROM document_kinds WHERE document_id=?",
            (doc_id,),
        )
        .fetchone()
    )
    return row["kind"], row["state"], json.loads(row["evidence"] or "{}")


def _role(doc_id):
    row = (
        db.connect()
        .execute(
            "SELECT document_role FROM document_classification WHERE document_id=?",
            (doc_id,),
        )
        .fetchone()
    )
    return row["document_role"] if row else None


def test_the_role_follows_the_kind_or_the_page_and_a_disagreement_is_named():
    assert document_kind.suggest_role("contract", None)["role"] == "CONTRACT_DOCUMENT"
    assert document_kind.suggest_role("contract", "documents")["basis"] == "kind"
    page = document_kind.suggest_role("contract", "review")
    assert (page["role"], page["basis"], page["kind_says"]) == (
        "CONTRACTOR_SUBMITTAL",
        "page",
        "CONTRACT_DOCUMENT",
    )
    assert "kind_says" not in document_kind.suggest_role("datasheet", "review")
    assert document_kind.suggest_role("unknown", "documents") is None


def test_a_suggestion_is_stored_in_the_kind_evidence_and_never_as_a_role(on):
    _doc("c1", CONTRACT_COVER, state=doc_router.STATE_NEEDS_ENGINEER)
    got = document_kind.suggest_kind_and_role("c1")
    assert got["role"] == "CONTRACT_DOCUMENT" and got["basis"] == "kind"
    kind, state, ev = _evidence("c1")
    assert (kind, state) == ("contract", doc_router.STATE_SUGGESTED) and ev[
        "role_suggestion"
    ]["role"] == "CONTRACT_DOCUMENT"
    assert _role("c1") is None  # never a role: the approved list reads the role only
    assert "c1-sha" not in claude_approved.approved_hashes()


def test_the_page_it_came_in_on_is_kept_and_used(on):
    _doc("c2", CONTRACT_COVER, state=doc_router.STATE_NEEDS_ENGINEER)
    assert document_kind.record_upload_context("c2", "review")
    got = document_kind.suggest_kind_and_role("c2")
    assert (got["role"], got["basis"], got["kind_says"]) == (
        "CONTRACTOR_SUBMITTAL",
        "page",
        "CONTRACT_DOCUMENT",
    )
    assert (
        document_kind.record_upload_context("c2", "nowhere") is False
    )  # an unknown page is not kept


def test_a_file_with_a_role_or_a_confirmed_kind_is_respected(on):
    _doc(
        "s1",
        DATASHEET_COVER,
        role="CONTRACTOR_SUBMITTAL",
        kind="datasheet",
        state=doc_router.STATE_SUGGESTED,
    )
    assert document_kind.suggest_kind_and_role("s1") is None
    assert _evidence("s1")[2] == {"cue": "router"}
    _doc("k1", CONTRACT_COVER, kind="procedure", state=doc_router.STATE_CONFIRMED)
    assert (
        document_kind.suggest_kind_and_role("k1")["role"] == "CONTRACTOR_SUBMITTAL"
    )  # the confirmed kind decides
    kind, state, ev = _evidence("k1")
    assert (kind, state) == ("procedure", doc_router.STATE_CONFIRMED) and ev[
        "cue"
    ] == "router"


def test_switch_off_writes_nothing_anywhere():
    _doc("c3", CONTRACT_COVER, state=doc_router.STATE_NEEDS_ENGINEER)
    assert document_kind.suggest_kind_and_role("c3") is None
    assert document_kind.record_upload_context("c3", "review") is False
    document_kind.after_upload("c3", "review", True)
    document_kind.after_read_in("c3")
    assert _evidence("c3") == (None, doc_router.STATE_NEEDS_ENGINEER, {"cue": "router"})
    assert not (settings.data_dir / document_kind.CONTEXT_FILE).exists()


def test_the_route_says_the_switch_and_the_review_roles(monkeypatch):
    client = TestClient(app)
    assert client.get("/api/document-kinds/role-suggestion").json() == {
        "enabled": False,
        "review_roles": ["CONTRACTOR_SUBMITTAL"],
    }
    monkeypatch.setattr(settings, "upload_role_suggestion_enabled", True)
    assert client.get("/api/document-kinds/role-suggestion").json() == {
        "enabled": True,
        "review_roles": ["CONTRACTOR_SUBMITTAL", "CONTRACT_DOCUMENT"],
    }


def test_switch_off_the_upload_answer_is_byte_same_with_or_without_the_page_field():
    client = TestClient(app)
    plain = client.post(
        "/api/documents",
        files={"file": ("a.pdf", io.BytesIO(pdf_bytes()), "application/pdf")},
    )
    again = client.post(
        "/api/documents",
        files={"file": ("a.pdf", io.BytesIO(pdf_bytes()), "application/pdf")},
        data={"uploaded_from": "review"},
    )
    assert plain.status_code == again.status_code == 200
    first, second = plain.json(), again.json()
    assert second["duplicate_of"] == first["document"]["id"]
    assert second["document"] == first["document"]
    assert not (settings.data_dir / document_kind.CONTEXT_FILE).exists()


def test_switch_on_the_upload_keeps_the_page(on):
    client = TestClient(app)
    r = client.post(
        "/api/documents",
        files={"file": ("b.pdf", io.BytesIO(pdf_bytes()), "application/pdf")},
        data={"uploaded_from": "standards"},
    )
    assert r.status_code == 200
    assert document_kind.upload_context(r.json()["document"]["id"]) == "standards"


def test_a_reading_never_replaces_a_stored_contract_kind(on):
    """Review R104 (rule 1): a no-role paper with a stored "contract" kind whose text now reads as a datasheet (an OCR re-route
    changed it) keeps "contract"; an ordinary stored guess is still replaced (the control)."""
    _doc("c_ocr", DATASHEET_COVER, kind="contract", state=doc_router.STATE_SUGGESTED)
    _doc("p_ocr", DATASHEET_COVER, kind="procedure", state=doc_router.STATE_SUGGESTED)
    assert (
        document_kind.decide_document_kind(
            [{"page_no": 1, "text": DATASHEET_COVER}]
        ).kind
        == "datasheet"
    )
    document_kind.after_read_in("c_ocr")
    document_kind.after_read_in("p_ocr")
    kind, state, evidence = _evidence("c_ocr")
    assert (kind, state) == ("contract", doc_router.STATE_SUGGESTED)
    assert evidence["role_suggestion"]["kind"] == "contract"
    assert _evidence("p_ocr")[0] == "datasheet"
