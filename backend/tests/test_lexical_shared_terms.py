"""The shared-terms threshold for longer questions.

Refusal calibration on the real corpus (2026-09-29) found four absent-topic
questions answered confidently: each shared exactly one distinctive term with
an unrelated passage, and one match was enough under the old rule (any single
covered, non-common term made the gate pass, however long the question was).
A question naming three or more distinctive terms now needs two of them
shared with the passage; a shorter question still needs only one.
"""

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import db, keyword, lexical
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
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()

#: One page holding every term these tests need present in the corpus
#: somewhere, so `keyword.term_occurrences` finds them and the gate reaches
#: the shared-terms check instead of refusing on "absent from the corpus".
TERMS_PAGE = [
    "9", "General provisions",
    "The minimum coating thickness for storage tank shells is defined",
    "elsewhere in this standard and is not repeated on this page.",
    "10", "Miscellaneous",
    "The valve tank drain shall be checked for leaks every month.",
    "11", "Storage",
    "The coating storage area shall be dry and ventilated at all times.",
]


def upload(client, blocks, name="spec.pdf") -> str:
    path = settings.data_dir / name
    doc = pymupdf.open()
    for block in blocks:
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
    return doc_id


def _scope():
    from app.search import every_document_id
    return every_document_id()


#: what is the minimum coating thickness for the storage tank
#: -> distinctive terms: minimum, coating, thickness, storage, tank (5, >= 3)
QUESTION = "what is the minimum coating thickness for the storage tank"


def test_a_long_question_sharing_only_one_term_is_now_refused():
    """The exact shape of the four false answers the calibration run found:
    a passage about something else that happens to share one word."""
    client = TestClient(app)
    upload(client, [TERMS_PAGE])

    # Shares only "tank" with QUESTION's five distinctive terms.
    off_topic_passage = "The valve tank drain shall be checked for leaks every month."

    verdict = lexical.assess(QUESTION, off_topic_passage, allowed_document_ids=_scope())
    assert verdict["ok"] is False, verdict
    assert "tank" in verdict["covered"]
    assert verdict["reason"]


def test_a_long_question_sharing_two_terms_is_still_answered():
    """The bar moved from one to two - not to three. A passage sharing two
    of the question's terms must still pass, or the fix overshot."""
    client = TestClient(app)
    upload(client, [TERMS_PAGE])

    # Shares "coating" and "storage" with QUESTION's five distinctive terms.
    on_topic_passage = "The coating storage area shall be dry and ventilated at all times."

    verdict = lexical.assess(QUESTION, on_topic_passage, allowed_document_ids=_scope())
    assert verdict["ok"] is True, verdict
    assert {"coating", "storage"} <= set(verdict["covered"])


def test_a_short_question_still_needs_only_one_shared_term():
    """Fewer than three distinctive terms: the original, looser rule stays -
    a short question has less to share in the first place."""
    client = TestClient(app)
    upload(client, [TERMS_PAGE])

    # Two distinctive terms only: "coating", "tank".
    short_question = "coating on the tank"
    passage = "The valve tank drain shall be checked for leaks every month."

    verdict = lexical.assess(short_question, passage, allowed_document_ids=_scope())
    assert verdict["ok"] is True, verdict
