"""A request for advice is not a failed document question.

    "i would like to implement FEED documentation for an EPC project, can you
     please help me with that?"

was searched, refused, and reported as

    "The documents do not answer this
     the closest passages were not a credible match. Nothing was made up to
     fill the gap."

Every clause of that describes something that did not happen. The reader never
asked what a document says, so the corpus was not what fell short, and the
passages were not "the closest match" to a question about their content - they
were the closest match to a question that was not about content at all.

Refusing is right. Describing the refusal falsely is the defect, and it is the
same class of defect as an invented citation: a confident sentence about
something the system did not do.

The model these tests hold the new wording to is this project's best refusal:

    "ABAP does not appear anywhere in the indexed documents. If it is an
     abbreviation, try the full term."

Specific, honest, and it tells the reader what to try next. Its own behaviour
is asserted here unchanged, because a fix that quietly moves an existing
refusal is not a fix.
"""

import fitz
import pytest
from fastapi.testclient import TestClient

from app import answer as answer_mod
from app import db, intent, keyword
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

SPEC = [
    "3.2 Abbreviations",
    "MDFT minimum dry film thickness NDFT nominal dry film thickness",
    "NACE National Association of Corrosion Engineers RAL colour definition",
    "CPS coating procedure specification CPT coating procedure test applies",
    "throughout this specification wherever the abbreviation is used in text.",
]

SYSTEM_ONE = [
    "A.1 Coating system no. 1",
    "Coating system no. 1 shall have a nominal dry film thickness of 280 um",
    "applied as three coats over blast cleaned carbon steel in atmospheric",
    "service, and the zinc rich primer shall be in accordance with ISO 12944-5",
    "before any topcoat is applied to the prepared surface of the component.",
]

#: The question from the defect report, verbatim.
ADVICE = (
    "i would like to implement FEED documentation for an EPC project, "
    "can you please help me with that?"
)


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


def upload(client, blocks=(SPEC, SYSTEM_ONE)) -> str:
    path = settings.data_dir / "spec.pdf"
    doc = fitz.open()
    for block in blocks:
        page = doc.new_page()
        for i, line in enumerate(block):
            page.insert_text((72, 100 + i * 16), line)
    doc.save(str(path))
    doc.close()
    with open(path, "rb") as fh:
        doc_id = client.post(
            "/api/documents", files={"file": ("spec.pdf", fh, "application/pdf")}
        ).json()["document"]["id"]
    IngestionWorker().process(doc_id)
    return doc_id


def ask(client, question: str) -> dict:
    convo = client.post("/api/conversations").json()
    return client.post(
        f"/api/conversations/{convo['id']}/ask", json={"question": question}
    ).json()


def _scope() -> frozenset[str]:
    from app import search as search_mod

    return search_mod.every_document_id()


# ------------------------------------------------ the request for advice


def test_a_request_for_advice_is_classified_as_one():
    assert intent.classify(ADVICE) == intent.ADVICE_REQUEST


@pytest.mark.parametrize(
    "text",
    [
        ADVICE,
        "can you help me write a coating procedure specification for this job",
        "how do i set up a document control process for the project",
        "we need to develop a commissioning plan, please help us",
    ],
)
def test_advice_requests_are_recognised(text):
    assert intent.classify(text) == intent.ADVICE_REQUEST


def test_the_advice_reply_says_what_actually_happened():
    """Not "the documents do not answer this" - the corpus was never asked."""
    client = TestClient(app)
    upload(client)
    body = ask(client, ADVICE)

    # `guidance`, not `insufficient_evidence`. The frontend prints "The
    # documents do not answer this" for insufficient_evidence and nothing of
    # the kind for guidance, so the answer_type IS the wording.
    assert body["answer_type"] == "guidance"
    assert body["input_kind"] == "advice_request"

    text = body["answer"]
    assert "request for help with a task" in text
    assert "not a question about what the documents say" in text
    # the old, false description must not appear in any form
    assert "credible match" not in text.lower()
    assert "do not answer" not in text.lower()


def test_the_advice_request_is_never_searched():
    """Nothing was retrieved, so nothing may be shown as considered. A refusal
    costs a rerank; this must cost nothing."""
    called = []
    original = answer_mod.search_mod.search
    try:
        answer_mod.search_mod.search = lambda *a, **k: called.append(1) or {}
        result = answer_mod.answer(ADVICE, allowed_document_ids=_scope())
    finally:
        answer_mod.search_mod.search = original

    assert called == [], "an advice request must not reach retrieval"
    assert result["answer_type"] == "guidance"
    assert result["retrieval_mode"] == "not_searched"
    assert result["candidates_considered"] == 0
    assert result["passages"] == []
    assert result["reason"] is None


def test_the_advice_reply_answers_nothing_and_invents_nothing():
    """The worst possible fix for this defect is one that starts helping."""
    client = TestClient(app)
    upload(client)
    body = ask(client, ADVICE)
    text = body["answer"].lower()

    # No content about the subject the reader raised. If any of these appears,
    # the reply has begun to answer from the model rather than from documents.
    for word in ("feed", "epc", "front end engineering", "deliverable",
                 "basis of design", "hazop", "p&id", "workflow", "stage gate"):
        assert word not in text, f"the reply started answering: {word!r}"

    # No invented procedure: a numbered or bulleted set of steps is the shape
    # advice takes, and the only bullets allowed here are the example
    # questions, which are drawn from documents that are actually loaded.
    lead = body["answer"].split("Try one of these:")[0]
    assert "1." not in lead and "•" not in lead and "\n-" not in lead
    for example in body["examples"]:
        assert "spec.pdf" in example

    # No evidence, no coverage table, no score, nothing that could read as a
    # finding. A coverage report under a non-search would invite the reader to
    # read it as evidence the corpus could have answered.
    assert body["passages"] == []
    assert body["passage"] is None
    assert body.get("coverage") is None
    assert body.get("cited") in (None, [])
    assert body.get("complete") is not True


# --------------------------------------------- what must NOT change


def test_a_polite_document_question_is_still_a_document_question():
    """The false positive that would matter most: telling a reader asking a
    fair question about their own documents that they were not asking about
    their documents. Politeness is not a task."""
    question = "can you tell me what the coating thickness is?"
    assert intent.classify(question) == intent.DOCUMENT_QUESTION

    client = TestClient(app)
    upload(client)
    body = ask(client, question)

    assert body["answer_type"] != "guidance"
    assert body["input_kind"] is None
    assert body["retrieval_mode"] != "not_searched"


@pytest.mark.parametrize(
    "text",
    [
        "what is the NDFT for coating system no. 1",
        "what does clause 5.3.2 require",
        "is a zinc rich primer required",
        "can you help me find what the spec says about the primer",
        "how should i prepare the surface before coating",
        "hi-lo alarm setpoint for the separator",
    ],
)
def test_a_real_question_is_never_classified_as_advice(text):
    """Over-classifying is the worse failure. A lookup marker anywhere vetoes
    the advice branch, however polite the wrapper around it."""
    assert intent.classify(text) == intent.DOCUMENT_QUESTION


def test_the_unknown_term_refusal_is_unchanged():
    """The refusal this fix is modelled on must still fire for its own case,
    with its own wording and its own answer_type."""
    client = TestClient(app)
    upload(client)
    body = ask(client, "what is ABAP")

    assert body["answer_type"] == "insufficient_evidence"
    assert body["input_kind"] is None
    assert body["answer"] is None
    reason = body["reason"]
    assert "ABAP" in reason
    assert "does not appear anywhere in the indexed documents" in reason
    assert "If it is an abbreviation, try the full term" in reason


def test_the_greeting_reply_is_unchanged():
    client = TestClient(app)
    upload(client)
    body = ask(client, "hi")
    assert body["answer_type"] == "guidance"
    assert body["input_kind"] == "greeting"
    assert "Hello." in body["answer"]
