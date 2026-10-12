"""A standard rarely quotes its own file name.

Reproduced on the owner's PC, twice: "what does SAES-W-010 say about post
weld heat treatment" was refused with "SAES-W-010 does not appear anywhere in
the indexed documents", while the same answer card listed that standard's own
pages as read. The cause: `lexical.assess`'s named-subject check counts an
identifier as absent when it is never printed INSIDE any chunk's text -
`keyword.term_occurrences` is a content search, and a standard's own pages
almost never spell out its own designation. The document is not missing; the
document's own text just never says its own name.

Fix: before calling an identifier-shaped term absent, check whether it names
a document that is already indexed AND permitted (by filename, the same
`understanding.designation` the rest of the system already uses to recognise
"our SAES-W-010" in a question). If so, it is present - the reader named a
real source, and the question searches inside it - not absent.
"""

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import answer as answer_mod
from app import db, keyword, lexical
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

#: The standard's own pages. Never once prints "SAES-W-010" - real standards
#: are headed by their title and clause numbers, not their own file name.
PAGES = [
    "7.4 Post Weld Heat Treatment",
    "Post weld heat treatment shall be performed in accordance with the",
    "heating and cooling rates given in Table 4, and the holding temperature",
    "shall be maintained for the duration specified for the material grade",
    "and thickness of the components being welded together in this section.",
]

UNRELATED = [
    "3.1 Scope",
    "This specification covers general requirements for pressure vessels",
    "used in hydrocarbon processing service across onshore facilities and",
    "does not apply to piping systems covered by other specifications.",
]


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def upload(client, blocks, name) -> str:
    path = settings.data_dir / name
    doc = pymupdf.open()
    for block in blocks:
        page = doc.new_page()
        for i, line in enumerate(block):
            page.insert_text((72, 100 + i * 16), line)
    doc.save(str(path))
    doc.close()
    with open(path, "rb") as fh:
        doc_id = client.post(
            "/api/documents", files={"file": (name, fh, "application/pdf")}
        ).json()["document"]["id"]
    IngestionWorker().process(doc_id)
    return doc_id


def _scope():
    from app.search import every_document_id
    return every_document_id()


def test_the_defect_a_standards_own_pages_never_print_its_own_name(monkeypatch):
    """THE CAUSE, proven directly: a document indexed as SAES-W-010, whose own
    pages never print "SAES-W-010", is counted absent by content search alone."""
    client = TestClient(app)
    upload(client, [PAGES], "SAES-W-010.pdf")

    # The content search this defect relies on: the term really is absent
    # from every chunk's TEXT, confirming the document itself never quotes
    # its own name (the premise of the bug, not just its symptom).
    assert keyword.term_occurrences("SAES-W-010", allowed_document_ids=_scope()) == 0


def test_a_question_naming_an_indexed_standard_is_not_refused(monkeypatch):
    """THE MUTATION TARGET: the fixed behaviour. SAES-W-010 is indexed and
    permitted, so naming it is not a missing identifier - the gate must pass,
    and the real answer must come from inside that standard."""
    client = TestClient(app)
    upload(client, [PAGES], "SAES-W-010.pdf")
    upload(client, [UNRELATED], "unrelated-spec.pdf")

    verdict = lexical.assess(
        "what does SAES-W-010 say about post weld heat treatment",
        "Post weld heat treatment shall be performed in accordance with the "
        "heating and cooling rates given in Table 4.",
        allowed_document_ids=_scope(),
    )
    assert verdict["ok"] is True, verdict
    assert "SAES-W-010" not in verdict["absent_from_corpus"]

    result = answer_mod.answer(
        "what does SAES-W-010 say about post weld heat treatment",
        allowed_document_ids=_scope())
    assert result["answer_type"] == "extract"
    assert "does not appear anywhere" not in (result.get("reason") or "")


def test_a_standard_not_in_the_library_still_refuses(monkeypatch):
    """NOT VACUOUS: the honest refusal must survive. A standard genuinely
    absent from the library - not merely quiet about its own name - is still
    reported as absent, not silently waved through."""
    client = TestClient(app)
    upload(client, [UNRELATED], "unrelated-spec.pdf")

    verdict = lexical.assess(
        "what does SAES-Q-999 say about post weld heat treatment",
        "Post weld heat treatment shall be performed in accordance with the "
        "heating and cooling rates given in Table 4.",
        allowed_document_ids=_scope(),
    )
    assert verdict["ok"] is False
    assert "SAES-Q-999" in verdict["absent_from_corpus"]
    assert "does not appear anywhere in the indexed documents" in verdict["reason"]


def test_the_named_standard_check_respects_the_callers_permissions(monkeypatch):
    """CLAUDE.md rule 5: a filter may only NARROW what a caller may already
    read. A standard indexed but OUTSIDE this caller's own scope is not
    theirs to be told exists - it is reported exactly as if it were absent.

    A fully empty scope abstains earlier (`indexed_count` is 0), so this
    grants exactly one OTHER document - enough to reach the named-subject
    check itself, without granting the one being asked about."""
    client = TestClient(app)
    upload(client, [PAGES], "SAES-W-010.pdf")
    other_id = upload(client, [UNRELATED], "unrelated-spec.pdf")

    verdict = lexical.assess(
        "what does SAES-W-010 say about post weld heat treatment",
        "Post weld heat treatment shall be performed in accordance with the "
        "heating and cooling rates given in Table 4.",
        allowed_document_ids=frozenset({other_id}),
    )
    assert verdict["ok"] is False
    assert "SAES-W-010" in verdict["absent_from_corpus"]
