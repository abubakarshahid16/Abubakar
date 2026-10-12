"""#693: the document-type router has a "standard" kind, and a document already
classified COMPANY_STANDARD is not suggested as a procedure.

All documents here are INVENTED. Mutations: M4921-M4926,
`python scripts/mutation_check.py --phase 4921`.
"""
from __future__ import annotations

import secrets

import pytest

from app import access, db, doc_router
from app.config import settings

NOW = "2026-10-09T00:00:00Z"

# A standard written like a procedure: numbered clauses and "shall" throughout,
# which is what the 111 wrongly suggested documents looked like.
CLAUSES = [
    "Piping Fabrication Requirements\nScope\nThis document covers shop welding.\n"
    "1. The welder shall hold a current qualification.\n2. Welds shall be examined.\n"
    "3. The inspector shall record results.\n4. Records shall be kept.\n"
    "5. Repairs shall be approved.\n6. Tests shall be witnessed.\nPurpose of the rules is safety."]
PLAIN_STANDARD = [
    "Gate Valves\nRevision 3",
    "Foreword\nNormative references\nTerms and definitions\nThis specification covers gate valves."]
PROCEDURE = [
    "Work Instruction - Line Isolation\nPurpose\nTo isolate a line safely.\nScope\nAll lines.\n"
    "Responsibilities\nThe operator shall confirm the permit.\n"
    "1. Close the upstream valve.\n2. Open the vent.\n3. Verify zero pressure.\n"
    "4. The supervisor must sign the permit.\nPrecautions apply."]


def test_a_document_classified_as_a_company_standard_is_a_standard_not_a_procedure():
    without = doc_router.route("pfr.pdf", CLAUSES)
    assert without.kind != "standard"          # the text alone reads like a procedure
    r = doc_router.route("pfr.pdf", CLAUSES, "COMPANY_STANDARD")
    assert r.kind == "standard" and r.state == "suggested"


def test_a_standard_without_a_recorded_role_is_still_read_as_a_standard():
    r = doc_router.route("valve-spec.pdf", PLAIN_STANDARD)
    assert r.kind == "standard"


def test_the_role_cue_does_not_turn_a_procedure_into_a_standard():
    r = doc_router.route("isolation.pdf", PROCEDURE, "PROJECT_DOCUMENT")
    assert r.kind == "procedure"
    assert doc_router.route("isolation.pdf", PROCEDURE).kind == "procedure"


def test_the_vocabulary_offers_standard_as_a_kind():
    assert "standard" in [k["id"] for k in doc_router.kinds()]


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


def _doc(doc_id, filename, pages, role=None):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES (?,?,?,1,?,'ready',?,?)",
            (doc_id, filename, f"sha-{doc_id}", filename, len(pages), NOW))
        for i, text in enumerate(pages, start=1):
            conn.execute("INSERT INTO pages (document_id,page_no,text,char_count,batch_no) VALUES (?,?,?,?,0)",
                         (doc_id, i, text, len(text)))
        if role:
            conn.execute("INSERT INTO document_classification (document_id, document_role, suggested_by) VALUES (?,?,'test')",
                         (doc_id, role))


def test_routing_stored_documents_reads_the_recorded_role(temp_db):
    _doc("s1", "pfr.pdf", CLAUSES, role="COMPANY_STANDARD")
    _doc("p1", "iso.pdf", PROCEDURE)
    doc_router.route_document("s1")
    doc_router.route_document("p1")
    rows = doc_router.of_documents(["s1", "p1"])
    assert rows["s1"]["document_kind"] == "standard"
    assert rows["p1"]["document_kind"] == "procedure"


def test_no_company_standard_carries_a_procedure_suggestion_after_a_router_version_change(temp_db):
    """The live case: suggestions made by version 1 are re-read by version 2."""
    _doc("s1", "pfr.pdf", CLAUSES, role="COMPANY_STANDARD")
    version = str(doc_router.vocabulary()["router_version"])
    assert version != "1"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO document_kinds (document_id, kind, state, evidence, router_version, routed_at)"
            " VALUES ('s1','procedure','suggested','{}','1',?)", (NOW,))
    out = doc_router.route_unrouted()
    assert out["routed"] == 1
    assert doc_router.of_documents(["s1"])["s1"]["document_kind"] == "standard"


def test_a_confirmed_procedure_on_a_standard_is_left_to_the_person(temp_db):
    _doc("s1", "pfr.pdf", CLAUSES, role="COMPANY_STANDARD")
    doc_router.confirm("s1", "procedure", None)
    assert doc_router.route_document("s1") is None
    assert doc_router.of_documents(["s1"])["s1"]["document_kind"] == "procedure"
