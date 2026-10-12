"""Abbreviations and spelled-out terms find each other (R3 retrieval fix).

THE DEFECT, on invented data. A standard (STD-A-001, "Positive Material
Identification") has an acronym list passage
"PWHT Post-Weld Heat Treatment PMI Positive Material Identification ..." and a
clause "When heat treating is performed after PMI, the identification marking
must be recognizable after heat treatment." A question "What does STD-A-001
say about PWHT" was refused although the scope was that one standard.

Three causes, all fixed at the class level:

  1. acronyms.py never harvested a row whose expansion has a capitalised
     hyphenated word ("Post-Weld"), so PWHT had no expansion.
  2. The keyword side REQUIRED the identifier "STD-A-001" inside a passage,
     and a standard never prints its own designation: 0 keyword candidates
     inside the very document the question named.
  3. The reranker scored the question as typed ("PWHT") against passages that
     spell the term out, below the credibility floor.

All data here is invented.
"""

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import acronyms, db, keyword, lexical
from app import answer as answer_mod
from app import search as search_mod
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    acronyms.reset_cache()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()
    acronyms.reset_cache()


def upload(client, pages, name) -> str:
    path = settings.data_dir / name
    doc = pymupdf.open()
    for block in pages:
        page = doc.new_page()
        for i, line in enumerate(block):
            page.insert_text((72, 90 + i * 15), line)
    doc.save(str(path))
    doc.close()
    with open(path, "rb") as fh:
        doc_id = client.post(
            "/api/documents", files={"file": (name, fh, "application/pdf")}
        ).json()["document"]["id"]
    IngestionWorker().process(doc_id)
    acronyms.reset_cache()
    return doc_id


def scope() -> frozenset[str]:
    return search_mod.every_document_id()


FILLER = ["9.9", "Scope", "This standard covers welding of pressure piping in",
          "hydrocarbon service and applies to new construction only."]
OTHER = ["3.1", "Scope", "General requirements for pressure vessels used in",
         "onshore facilities and their supporting structures."]

ACRONYM_LIST = ["4.1", "Acronyms",
                "PWHT Post-Weld Heat Treatment PMI Positive Material Identification",
                "NDE Non-Destructive Examination WPS Welding Procedure Specification",
                "PQR Procedure Qualification Record ITP Inspection and Test Plan"]
CLAUSE = ["5.2",
          "When heat treating is performed after PMI, the identification marking must be",
          "recognizable after heat treatment."]


#: Padding so the acronym page is long enough to be kept as a passage.
PAD = ["WPS Welding Procedure Specification PQR Procedure Qualification Record",
       "ITP Inspection and Test Plan FAT Factory Acceptance Test",
       "SAT Site Acceptance Test HAZ Heat Affected Zone"]


def library_a(client) -> str:
    doc = upload(client, [ACRONYM_LIST, CLAUSE, FILLER], "STD-A-001.pdf")
    upload(client, [OTHER], "other-spec.pdf")
    return doc


def texts(result) -> str:
    """Every passage an extract answer carries as evidence."""
    rows = [result.get("passage") or {}, *(result.get("answer_passages") or []),
            *(result.get("supporting") or []), *(result.get("passages") or [])]
    return " ".join(r.get("text", "") for r in rows)


def test_abbreviation_question_returns_the_acronym_and_the_clause_passage():
    """THE DEFECT. Fails without the fix: extract tier refused."""
    client = TestClient(app)
    doc = library_a(client)
    result = answer_mod.answer(
        "What does STD-A-001 say about PWHT", document_id=doc,
        allowed_document_ids=scope())
    assert result["answer_type"] == "extract", result.get("reason")
    shown = texts(result)
    assert "Post-Weld Heat Treatment" in shown
    assert "recognizable after heat treatment" in shown


def test_a_hyphenated_capitalised_expansion_is_harvested_from_the_library():
    """Cause 1, with an abbreviation the built-in list does NOT know, so only
    the harvest can supply it."""
    client = TestClient(app)
    upload(client, [["4.1", "Acronyms",
                     "ZQE Zonal-Quality Examination ZRB Zone Root Bend",
                     "ZPT Zone Pressure Test ZMS Zone Marking Standard", *PAD], FILLER],
           "STD-Z-009.pdf")
    found = acronyms.harvest(allowed_document_ids=scope())
    assert "zonal-quality examination" in found.get("ZQE", set())


def test_the_named_documents_own_designation_does_not_empty_the_keyword_side():
    """Cause 2: keyword candidates only (no dense, no rerank)."""
    client = TestClient(app)
    doc = library_a(client)
    result = search_mod.search(
        "What does STD-A-001 say about PWHT", document_id=doc,
        allowed_document_ids=scope(), dense=False, rerank=False)
    assert result["keyword_candidates"] >= 1
    assert any("Post-Weld Heat Treatment" in h["text"] for h in result["hits"])
    # the clause that never writes PWHT nor "post weld": found by the tail of
    # the spelled-out form ("heat treatment"), as a CANDIDATE
    assert any("recognizable after heat treatment" in h["text"] for h in result["hits"])


def test_a_builtin_abbreviation_matches_a_passage_that_spells_it_out():
    """The library never defines PWHT; the built-in list only widens the match."""
    client = TestClient(app)
    doc = upload(client, [
        ["6.2", "Welding", "Post weld heat treatment shall be carried out before",
         "any hydrostatic test of the completed assembly."], FILLER], "STD-B-002.pdf")
    result = search_mod.search(
        "What does STD-B-002 say about PWHT", document_id=doc,
        allowed_document_ids=scope(), dense=False, rerank=False)
    assert any("heat treatment shall be carried out" in h["text"] for h in result["hits"])


def test_an_abbreviation_nothing_in_scope_spells_out_still_refuses():
    """SAFETY. PWHT is on the built-in list, but this standard never mentions
    heat treatment and defines nothing: the expansion must not bypass the gate."""
    client = TestClient(app)
    doc = upload(client, [["8.1", "Painting", "Surface preparation shall be completed",
                           "before any primer is applied to the steel."], FILLER],
                 "STD-B-002.pdf")
    upload(client, [OTHER], "other-spec.pdf")
    for question in ("What does STD-B-002 say about PWHT",
                     "What does STD-B-002 say about ZQXW"):
        result = answer_mod.answer(
            question, document_id=doc, allowed_document_ids=scope())
        assert result["answer_type"] == "insufficient_evidence", question
        assert result["answer"] is None
    # and at the gate itself, whatever the semantic stage would have said
    verdict = lexical.assess(
        "What does STD-B-002 say about PWHT",
        "8.1 Painting Surface preparation shall be completed before any primer "
        "is applied to the steel.",
        document_id=doc, allowed_document_ids=scope())
    assert verdict["ok"] is False
    assert "PWHT" in verdict["absent_from_corpus"]


def test_a_scoped_refusal_names_the_document_it_searched():
    client = TestClient(app)
    doc = upload(client, [["8.1", "Painting", "Surface preparation shall be completed",
                           "before any primer is applied to the steel."], FILLER],
                 "STD-B-002.pdf")
    upload(client, [OTHER], "other-spec.pdf")
    result = answer_mod.answer(
        "What does STD-B-002 say about ZQXW", document_id=doc,
        allowed_document_ids=scope())
    reason = result["reason"]
    assert "STD-B-002.pdf" in reason and "passages searched" in reason, reason
    assert "none of the indexed documents" not in reason


def test_a_spelled_out_question_matches_an_abbreviation_only_passage():
    """The library defines RQT (not on the built-in list); the clause only
    ever writes the abbreviation."""
    client = TestClient(app)
    doc = upload(client, [
        ["4.1", "Acronyms", "RQT Root-Quality Test NDE Non-Destructive Examination", *PAD],
        ["7.3", "Records", "RQT shall be recorded for every weld before the joint",
         "is accepted by the inspector."], FILLER], "STD-C-003.pdf")
    # keyword side alone
    result = search_mod.search(
        "What does STD-C-003 say about root quality test", document_id=doc,
        allowed_document_ids=scope(), dense=False, rerank=False)
    assert any("RQT shall be recorded" in h["text"] for h in result["hits"])
    # and the lexical gate accepts the abbreviation-only clause as covering
    # the spelled-out term (the cross-encoder's own floor is a separate,
    # calibrated stage and is not what this test is about)
    verdict = lexical.assess(
        "What does STD-C-003 say about root quality test",
        "7.3 Records RQT shall be recorded for every weld before the joint "
        "is accepted by the inspector.",
        document_id=doc, allowed_document_ids=scope())
    assert verdict["ok"] is True, verdict
    assert "root quality test" in verdict["covered"]


def test_the_typed_term_is_never_removed_by_expansion():
    """Expansion only ADDS: a passage that writes only the typed abbreviation
    is still found."""
    client = TestClient(app)
    doc = upload(client, [
        ["4.1", "Acronyms", "RQT Root-Quality Test NDE Non-Destructive Examination", *PAD],
        ["7.3", "Records", "RQT shall be recorded for every weld before the joint",
         "is accepted by the inspector."], FILLER], "STD-C-003.pdf")
    result = search_mod.search(
        "What does STD-C-003 say about RQT", document_id=doc,
        allowed_document_ids=scope(), dense=False, rerank=False)
    assert any("RQT shall be recorded" in h["text"] for h in result["hits"])
