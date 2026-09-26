"""B6C: question understanding - scope, clause references, ambiguity, fallback.

Understanding changes WHAT retrieval searches, never the answer:
  * a document named by its designation, or referred to ("this standard"),
    scopes the search - within the caller's permitted documents only;
  * "the next / previous / this clause" resolve from the previous turn's
    EVIDENCE (document and clause metadata, never its answer text);
  * a name matching several documents, a reference with nothing to resolve,
    and identical text in several documents are reported, not guessed;
  * anything not understood leaves the question exactly as typed.

Synthetic documents and names only. Mutations M804-M810.
"""
from __future__ import annotations

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import chat, db, keyword
from app import understanding as u
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

DOCS = {"d1": "ABC-D-012.pdf", "d2": "XYZ-K-500.pdf", "d3": "Plain notes.pdf"}
ALL = frozenset(DOCS)


# ------------------------------------------------------------ unit: scope

def test_a_document_named_by_its_designation_scopes_the_search():
    r = u.understand("In ABC-D-012 what is the design pressure?", allowed_document_ids=ALL, documents=DOCS)
    assert r.document_id == "d1" and r.scope_reason == "named in the question"


def test_the_name_is_matched_whatever_the_separators():
    r = u.understand("per abc d 012, the design pressure", allowed_document_ids=ALL, documents=DOCS)
    assert r.document_id == "d1"


def test_a_named_document_outside_the_grants_never_widens_the_scope():
    r = u.understand("In ABC-D-012 what is the design pressure?",
                     allowed_document_ids=frozenset({"d2"}), documents=DOCS)
    assert r.document_id is None and r.scope_ids is None


def test_a_name_matching_several_documents_chooses_none_of_them():
    docs = {"a": "ABC-D-012 Rev 1.pdf", "b": "ABC-D-012_2023.pdf", "c": "XYZ-K-500.pdf"}
    r = u.understand("what does ABC-D-012 say about vents", allowed_document_ids=frozenset(docs), documents=docs)
    assert r.document_id is None
    assert r.scope_ids == frozenset({"a", "b"}) and set(r.ambiguous_documents) == {"a", "b"}


def test_this_standard_refers_to_the_document_the_previous_answer_came_from():
    r = u.understand("what does this standard say about vents?", allowed_document_ids=ALL,
                     documents=DOCS, context=u.PriorContext(document_id="d2", clause="6.2.3"))
    assert r.document_id == "d2"


def test_this_standard_with_nothing_to_refer_to_is_not_guessed():
    r = u.understand("what does this standard say about vents?", allowed_document_ids=ALL, documents=DOCS)
    assert r.document_id is None and r.scope_ids is None and r.notes


def test_this_standard_never_resolves_to_a_document_outside_the_grants():
    r = u.understand("what does this standard say about vents?", allowed_document_ids=frozenset({"d1"}),
                     documents=DOCS, context=u.PriorContext(document_id="d2"))
    assert r.document_id is None


# ------------------------------------------------------------ unit: clauses

@pytest.mark.parametrize("question, clause", [
    ("and the next clause?", "6.2.4"),
    ("what about the previous clause", "6.2.2"),
    ("explain that requirement", "6.2.3"),
])
def test_clause_references_resolve_from_the_previous_evidence(question, clause):
    r = u.understand(question, allowed_document_ids=ALL, documents=DOCS,
                     context=u.PriorContext(document_id="d2", clause="6.2.3"))
    assert r.clause == clause
    assert r.retrieval_query.endswith(f"clause {clause}")
    assert r.document_id == "d2"


def test_an_explicit_clause_is_kept_and_the_question_is_not_rewritten():
    q = "what does clause 7.1 require?"
    r = u.understand(q, allowed_document_ids=ALL, documents=DOCS,
                     context=u.PriorContext(document_id="d2", clause="6.2.3"))
    assert r.clause == "7.1" and r.retrieval_query == q


def test_the_next_clause_with_no_earlier_clause_is_reported_not_invented():
    r = u.understand("and the next clause?", allowed_document_ids=ALL, documents=DOCS)
    assert r.clause is None and r.notes and r.retrieval_query == "and the next clause?"


def test_a_plain_question_passes_through_unchanged():
    q = "what is the corrosion allowance for carbon steel?"
    r = u.understand(q, allowed_document_ids=ALL, documents=DOCS)
    assert r.retrieval_query == q and r.document_id is None and r.clause is None and not r.notes


# ------------------------------------------------------ unit: duplicates

def test_identical_text_in_two_documents_is_reported():
    text = "All referenced codes shall be of the latest issue including all revisions unless stated."
    same = u.duplicated_across_documents([
        {"document_id": "d1", "text": text}, {"document_id": "d2", "text": text + " "},
        {"document_id": "d3", "text": "Something else entirely about drains."}])
    assert same == ["d1", "d2"]


def test_different_text_is_not_a_duplicate():
    assert u.duplicated_across_documents([
        {"document_id": "d1", "text": "Vents shall be DN 50 minimum on every vessel top head."},
        {"document_id": "d2", "text": "Drains shall be DN 25 minimum at every low point."}]) == []


# ------------------------------------------------ end to end through chat.ask

BOILER = ["3 References",
          "All referenced codes and standards shall be of the latest issue including all revisions",
          "addenda and supplements unless stated otherwise in the purchase order for this equipment."]


def _shown(result) -> list[dict]:
    """Every passage an answer shows, whichever tier produced it."""
    return [p for p in [result.get("passage"), *(result.get("supporting") or []),
                        *(result.get("passages") or [])] if p]


@pytest.fixture
def two_standards(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "b6c.sqlite")
    db.reset_connection(); db.init_db(); keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    ids = {}
    for name, own in (("ABC-D-012.pdf", ["6.2 Vents", "Every vessel shall have a top vent of DN 50 minimum",
                                          "fitted with a blind flange and a gasket rated for the service."]),
                      ("XYZ-K-500.pdf", ["6.2 Drains", "Every vessel shall have a bottom drain of DN 25 minimum",
                                          "fitted with a plugged valve and routed to the closed drain header."])):
        path = tmp_path / name
        pdf = pymupdf.open()
        for block in (BOILER, own):
            page = pdf.new_page()
            for i, line in enumerate(block):
                page.insert_text((72, 100 + i * 16), line)
        pdf.save(str(path)); pdf.close()
        with open(path, "rb") as fh:
            doc = client.post("/api/documents", files={"file": (name, fh, "application/pdf")}).json()["document"]["id"]
        IngestionWorker().process(doc)
        ids[name] = doc
    yield ids
    db.reset_connection()


def test_boilerplate_found_in_two_standards_is_flagged_not_silently_attributed(two_standards):
    allowed = frozenset(two_standards.values())
    convo = chat.create_conversation()
    result = chat.ask(convo["id"], "which edition of the referenced codes applies?", allowed_document_ids=allowed)
    ambiguity = result.get("scope_ambiguity")
    assert ambiguity, _shown(result)
    assert {d["document_id"] for d in ambiguity["documents"]} == allowed


def test_naming_the_standard_answers_from_that_standard_only(two_standards):
    allowed = frozenset(two_standards.values())
    convo = chat.create_conversation()
    result = chat.ask(convo["id"], "in XYZ-K-500 which edition of the referenced codes applies?",
                      allowed_document_ids=allowed)
    assert result["understanding"]["document_id"] == two_standards["XYZ-K-500.pdf"]
    assert _shown(result) and {p["document_id"] for p in _shown(result)} == {two_standards["XYZ-K-500.pdf"]}
    assert "scope_ambiguity" not in result


def test_a_follow_up_about_this_standard_stays_in_the_previous_answers_standard(two_standards):
    allowed = frozenset(two_standards.values())
    convo = chat.create_conversation()
    first = chat.ask(convo["id"], "what size is the bottom drain?", allowed_document_ids=allowed)
    assert _shown(first)[0]["document_id"] == two_standards["XYZ-K-500.pdf"]
    follow = chat.ask(convo["id"], "which edition of the referenced codes does this standard require?",
                      allowed_document_ids=allowed)
    assert follow["understanding"]["document_id"] == two_standards["XYZ-K-500.pdf"]
    assert {p["document_id"] for p in _shown(follow)} == {two_standards["XYZ-K-500.pdf"]}
    # the resolved scope is stored and shown with the question
    assert follow["understanding"]["scope_reason"] == "the document the previous answer came from"
