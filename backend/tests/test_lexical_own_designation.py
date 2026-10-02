"""A document's own designation is not a term its passages must repeat.

Found on the owner's library 2026-10-02 after batch C: a comparison side asks
"What does SAES-W-017 say about post weld heat treatment?" inside that ONE
standard. The designation counted as a third distinctive term, which pushed
the question over `LONG_QUESTION_TERM_COUNT` and demanded two shared terms
from a page that can only supply the topic (the standard prints its own
number on its cover, not on the page that answers). The right page was
refused: "shares only 1 of the 2 distinctive terms this question needs".

Fix: in a ONE-document scope the document's own designation (by file name) is
credited for every passage of that document. In any wider scope it is not.
"""

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import db, keyword, lexical
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

COVER = [
    "1.1 Scope",
    "This standard SAES-W-017 covers the welding of pressure vessels in all",
    "plants and facilities and supersedes every earlier revision of it.",
]
PWHT_PAGE = [
    "7.4 Thermal treatment",
    "Relieving shall be performed in accordance with the heating and cooling",
    "rates given in Table 4 and the holding temperature shall be maintained",
    "for the duration specified for the material grade.",
]
STRESS_PAGE = [
    "9.2 Residual stress",
    "Residual stress in the weld region is limited by the sequence of passes.",
]
OTHER = ["3.1 Scope", "General requirements for piping systems in onshore service."]
QUESTION = "What does SAES-W-017 say about stress relieving?"


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


PASSAGE = " ".join(PWHT_PAGE)


def test_the_answering_page_passes_inside_its_own_standard():
    """MUTATION TARGET: the standard prints its number on the cover only
    (so the term HAS occurrences and the filename branch is not reached), the
    answering page lacks it, and the page must still pass in a one-document
    scope."""
    client = TestClient(app)
    a = upload(client, [COVER, PWHT_PAGE, STRESS_PAGE], "SAES-W-017.pdf")
    assert keyword.term_occurrences("SAES-W-017", allowed_document_ids=frozenset({a})) > 0

    verdict = lexical.assess(QUESTION, PASSAGE, allowed_document_ids=frozenset({a}))
    assert verdict["ok"] is True, verdict


def test_the_credit_does_not_reach_a_wider_scope():
    """NOT VACUOUS: with two documents in scope a passage gets NO credit for
    a designation it does not print, so the stricter bar still applies."""
    client = TestClient(app)
    a = upload(client, [COVER, PWHT_PAGE, STRESS_PAGE], "SAES-W-017.pdf")
    b = upload(client, [OTHER], "other-spec.pdf")

    verdict = lexical.assess(QUESTION, PASSAGE, allowed_document_ids=frozenset({a, b}))
    assert verdict["ok"] is False, verdict


def test_an_unrelated_passage_in_the_one_document_scope_still_fails():
    """NOT VACUOUS: the credit is for the designation only. A passage that
    shares no topic term with the question is still refused."""
    client = TestClient(app)
    a = upload(client, [COVER, PWHT_PAGE, STRESS_PAGE, OTHER], "SAES-W-017.pdf")

    verdict = lexical.assess(
        QUESTION, "General requirements for piping systems in onshore service.",
        allowed_document_ids=frozenset({a}))
    assert verdict["ok"] is False, verdict
