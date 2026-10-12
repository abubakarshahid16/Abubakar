"""W5b-02 (#526): the document-type router.

All documents here are INVENTED. The router scores generic cues (file name,
title lines, body words, text shape) and either SUGGESTS a kind or ASKS the
engineer (kind left empty). A confirmed kind is never overwritten. The
confirm route is admin-gated and a kind is classification, not access control.

Mutations: M4301-M4314, `python scripts/mutation_check.py --phase 4301`.
"""
from __future__ import annotations

import json
import secrets

import pytest
from fastapi.testclient import TestClient

from app import access, auth, classification, db, doc_router
from app.config import settings
from app.main import app

NOW = "2026-10-09T00:00:00Z"

DATASHEET = [
    "DATA SHEET - Centrifugal Pump P-101\n"
    "Tag: P-101\nService: Cooling water\nDesign pressure: 12 bar\nDesign temperature: 80 C\n"
    "Flow: 120 m3/h\nHead: 45 m\nMaterial: carbon steel\nSpeed: 2900 rpm\nDriver power: 30 kW\n"
    "Operating conditions as above"]
PROCEDURE = [
    "Work Instruction - Line Isolation\nPurpose\nTo isolate a line safely.\nScope\nAll process lines.\n"
    "Responsibilities\nThe operator shall confirm the permit.\n"
    "1. Close the upstream valve.\n2. Open the vent.\n3. Verify zero pressure.\n"
    "4. The supervisor must sign the permit.\nPrecautions apply."]
LETTER = [
    "Dear Mr Example,\nSubject: Delay of delivery\nOur ref: AB-12\n"
    "We write to confirm the new date.\nKind regards,\nA. Writer"]
STUDY = [
    "Feasibility Study of Cooling Options\nMethodology\nThe approach compared three options.\n"
    "Assumptions\nWater is available.\nFindings\nOption two is cheapest.\nRecommendations\nProceed."]
AMBIGUOUS = ["Some text about nothing in particular. It has words but no clues."]


# ------------------------------------------------------------ pure routing

def test_a_datasheet_is_suggested_as_a_datasheet():
    r = doc_router.route("P-101.pdf", DATASHEET)
    assert r.kind == "datasheet" and r.state == "suggested"


def test_a_procedure_is_not_treated_as_a_datasheet():
    r = doc_router.route("isolation.pdf", PROCEDURE)
    assert r.kind == "procedure" and r.state == "suggested"


def test_a_letter_and_a_study_are_told_apart():
    assert doc_router.route("x.pdf", LETTER).kind == "letter"
    assert doc_router.route("x.pdf", STUDY).kind == "study"


def test_the_file_name_alone_can_carry_a_cue_but_not_a_decision():
    scores, _ = doc_router.score("pump_datasheet.pdf", AMBIGUOUS)
    assert scores["datasheet"] > 0
    r = doc_router.route("pump_datasheet.pdf", AMBIGUOUS)
    assert r.kind is None and r.state == "needs_engineer"


def test_an_unclear_document_asks_the_engineer_and_stores_no_kind():
    r = doc_router.route("misc.pdf", AMBIGUOUS)
    assert r.kind is None
    assert r.state == "needs_engineer"
    assert r.reason


def test_a_document_with_no_text_asks_the_engineer():
    r = doc_router.route("scan.pdf", ["", "  "])
    assert r.kind is None and r.state == "needs_engineer"
    assert "no text" in r.reason


def test_two_close_kinds_are_not_guessed(monkeypatch):
    vocab = json.loads(json.dumps(doc_router.vocabulary()))
    vocab["min_margin"] = 100
    monkeypatch.setattr(doc_router, "vocabulary", lambda: vocab)
    r = doc_router.route("P-101.pdf", DATASHEET)
    assert r.kind is None and r.state == "needs_engineer"
    assert "too close" in r.reason


def test_body_cues_are_capped_so_a_long_document_cannot_outvote_a_title():
    many = ["Introduction conclusion appendix executive summary " * 20]
    scores, _ = doc_router.score("x.pdf", many)
    assert scores["report"] <= doc_router.vocabulary()["body_cue_cap"]


def test_evidence_names_cues_and_never_quotes_the_document():
    r = doc_router.route("P-101.pdf", DATASHEET)
    blob = r.as_json()
    assert "cue" in blob
    assert "Cooling water" not in blob and "P-101" not in blob


# ------------------------------------------------------------------ storage

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", secrets.token_urlsafe(48))
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "router.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    access.set_user_resolver(None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()


def _doc(doc_id: str, filename: str, pages: list[str], status: str = "ready") -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES (?,?,?,1,?,?,?,?)",
            (doc_id, filename, f"sha-{doc_id}", filename, status, len(pages), NOW))
        for i, text in enumerate(pages, start=1):
            conn.execute(
                "INSERT INTO pages (document_id,page_no,text,char_count,batch_no) VALUES (?,?,?,?,0)",
                (doc_id, i, text, len(text)))


def test_routing_a_document_stores_its_suggestion(temp_db):
    _doc("d1", "P-101.pdf", DATASHEET)
    doc_router.route_document("d1")
    row = doc_router.of_documents(["d1"])["d1"]
    assert row["document_kind"] == "datasheet"
    assert row["document_kind_state"] == "suggested"
    assert row["document_kind_evidence"]["scores"]


def test_an_unclear_document_is_stored_as_needs_engineer_with_no_kind(temp_db):
    _doc("d1", "misc.pdf", AMBIGUOUS)
    doc_router.route_document("d1")
    row = doc_router.of_documents(["d1"])["d1"]
    assert row["document_kind"] is None
    assert row["document_kind_state"] == "needs_engineer"


def test_a_confirmed_kind_is_never_overwritten_by_a_routing_run(temp_db):
    _doc("d1", "P-101.pdf", DATASHEET)
    doc_router.route_document("d1")
    doc_router.confirm("d1", "report", None)
    assert doc_router.route_document("d1") is None
    row = doc_router.of_documents(["d1"])["d1"]
    assert row["document_kind"] == "report"
    assert row["document_kind_state"] == "confirmed"
    doc_router.route_unrouted()
    assert doc_router.of_documents(["d1"])["d1"]["document_kind"] == "report"


def test_an_unknown_kind_is_refused_by_name(temp_db):
    _doc("d1", "P-101.pdf", DATASHEET)
    with pytest.raises(doc_router.UnknownKind):
        doc_router.confirm("d1", "spaceship", None)
    assert doc_router.of_documents(["d1"]) == {}


def test_route_unrouted_routes_only_what_has_no_routing(temp_db):
    _doc("d1", "P-101.pdf", DATASHEET)
    _doc("d2", "w.pdf", PROCEDURE)
    _doc("d3", "pending.pdf", PROCEDURE, status="chunking")
    doc_router.route_document("d1")
    out = doc_router.route_unrouted()
    assert out["routed"] == 1
    assert "d2" in doc_router.of_documents(["d2"])
    assert doc_router.of_documents(["d3"]) == {}


def test_counts_cover_only_the_documents_a_caller_may_read(temp_db):
    _doc("d1", "P-101.pdf", DATASHEET)
    _doc("d2", "w.pdf", PROCEDURE)
    doc_router.route_unrouted()
    assert doc_router.counts(frozenset({"d1"}))["total"] == 1
    assert doc_router.counts(frozenset())["total"] == 0
    assert doc_router.counts(None)["total"] == 2
    assert doc_router.counts(None)["not_routed"] == 0


def test_classification_records_carry_the_kind(temp_db):
    _doc("d1", "P-101.pdf", DATASHEET)
    doc_router.route_document("d1")
    rec = classification.of_documents(["d1"])["d1"]
    assert rec["document_kind"] == "datasheet"
    assert rec["document_kind_state"] == "suggested"


def test_a_routing_failure_does_not_fail_ingestion(temp_db, monkeypatch):
    from app import ingest

    def boom(_):
        raise RuntimeError("router broke")

    monkeypatch.setattr(ingest.doc_router, "route_document", boom)
    result: dict = {}
    ingest._route_document_kind("d1", result)
    assert result["route_kind_error"] == "RuntimeError"


def test_ingestion_hook_records_the_routing_state(temp_db):
    from app import ingest
    _doc("d1", "P-101.pdf", DATASHEET)
    result: dict = {}
    ingest._route_document_kind("d1", result)
    assert result["route_kind"] == "suggested"


# ------------------------------------------------------------------- routes

def _user(user_id: str, *, is_admin: bool) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id,email,display_name,password_hash,is_active,created_at)"
            " VALUES (?,?,?,?,1,?)",
            (user_id, f"{user_id}@e.test", user_id.title(), auth._hasher.hash("router-pass"), NOW))
        if is_admin:
            conn.execute(
                "INSERT OR IGNORE INTO roles (id,name,description,kind,created_at)"
                " VALUES ('role_admin','admin','admins','capability',?)", (NOW,))
            conn.execute("INSERT OR IGNORE INTO user_roles (user_id,role_id,granted_at)"
                         " VALUES (?,'role_admin',?)", (user_id, NOW))


def _grant_all(user_id: str, doc_ids: list[str]) -> None:
    """Let the user read the documents, the way production grants it."""
    with db.connect() as conn:
        conn.execute("INSERT OR IGNORE INTO roles (id,name,description,kind,created_at)"
                     " VALUES ('role_eng','eng','eng','group',?)", (NOW,))
        conn.execute("INSERT OR IGNORE INTO user_roles (user_id,role_id,granted_at) VALUES (?,'role_eng',?)",
                     (user_id, NOW))
        for d in doc_ids:
            conn.execute("INSERT OR IGNORE INTO document_role_access (document_id,role_id,permission,granted_at)"
                         " VALUES (?,'role_eng','read',?)", (d, NOW))


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(auth.resolve_user_id)
    return TestClient(app)


def _headers(client: TestClient, user_id: str) -> dict:
    login = client.post("/api/auth/login", json={"email": f"{user_id}@e.test", "password": "router-pass"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_confirm_route_refuses_a_non_admin_and_changes_nothing(temp_db, monkeypatch):
    _doc("d1", "P-101.pdf", DATASHEET)
    doc_router.route_document("d1")
    _user("plain", is_admin=False)
    _grant_all("plain", ["d1"])
    client = _client(monkeypatch)
    r = client.put("/api/documents/d1/kind", json={"kind": "report"}, headers=_headers(client, "plain"))
    assert r.status_code == 404
    assert doc_router.of_documents(["d1"])["d1"]["document_kind"] == "datasheet"


def test_an_admin_confirms_and_the_record_says_so(temp_db, monkeypatch):
    _doc("d1", "P-101.pdf", DATASHEET)
    doc_router.route_document("d1")
    _user("boss", is_admin=True)
    _grant_all("boss", ["d1"])
    client = _client(monkeypatch)
    r = client.put("/api/documents/d1/kind", json={"kind": "report"}, headers=_headers(client, "boss"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["document_kind"] == "report" and body["document_kind_state"] == "confirmed"


def test_confirming_an_unknown_kind_is_a_422_naming_it(temp_db, monkeypatch):
    _doc("d1", "P-101.pdf", DATASHEET)
    _user("boss", is_admin=True)
    _grant_all("boss", ["d1"])
    client = _client(monkeypatch)
    r = client.put("/api/documents/d1/kind", json={"kind": "spaceship"}, headers=_headers(client, "boss"))
    assert r.status_code == 422
    assert "spaceship" in json.dumps(r.json())


def test_route_all_is_admin_only(temp_db, monkeypatch):
    _doc("d1", "P-101.pdf", DATASHEET)
    _user("plain", is_admin=False)
    _user("boss", is_admin=True)
    client = _client(monkeypatch)
    assert client.post("/api/admin/document-kinds/route", headers=_headers(client, "plain")).status_code == 404
    assert doc_router.of_documents(["d1"]) == {}
    ok = client.post("/api/admin/document-kinds/route", headers=_headers(client, "boss"))
    assert ok.status_code == 200 and ok.json()["routed"] == 1


def test_vocabulary_route_counts_only_what_the_caller_may_read(temp_db, monkeypatch):
    _doc("d1", "P-101.pdf", DATASHEET)
    _doc("d2", "w.pdf", PROCEDURE)
    doc_router.route_unrouted()
    _user("plain", is_admin=False)
    _grant_all("plain", ["d1"])
    client = _client(monkeypatch)
    body = client.get("/api/document-kinds", headers=_headers(client, "plain")).json()
    assert body["counts"]["total"] == 1
    assert {k["id"] for k in body["kinds"]} >= {"datasheet", "procedure", "letter"}


def test_the_worker_routes_a_document_right_after_it_is_chunked(temp_db, monkeypatch):
    """The hook is in `IngestionWorker.process`, not just in its helper."""
    from app import ingest

    class Stop(BaseException):
        pass

    _doc("d1", "P-101.pdf", DATASHEET, status="chunking")
    monkeypatch.setattr(ingest, "chunk_document", lambda _id: {"chunks_this_run": 1, "seconds": 0.0})
    monkeypatch.setattr(ingest.telemetry, "record", lambda *a, **k: None)
    seen: list[str] = []

    def fake_route(doc_id):
        seen.append(doc_id)
        raise Stop

    monkeypatch.setattr(ingest.doc_router, "route_document", fake_route)
    with pytest.raises(Stop):
        ingest.IngestionWorker().process("d1")
    assert seen == ["d1"]
