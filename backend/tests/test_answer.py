"""Two-tier answering: quote by default, generate on request, refuse otherwise."""

import fitz
import pytest
from fastapi.testclient import TestClient

from app import answer, db, keyword
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

VIBRATION = [
    "5.3.2 Vibration Limits",
    "Vibration limits per API 610 shall not exceed 3.0 mm/s RMS measured at the",
    "bearing housing of pump P-101A during continuous operation at rated flow.",
    "Any exceedance shall be reported to the area engineer before the pump is",
    "returned to service under the procedure given in this specification.",
]

MATERIALS = [
    "7.1 Materials of Construction",
    "Casing material shall be ASTM A216 WCB with an impeller of CA6NM and a",
    "shaft of AISI 4140 for all centrifugal pumps in hydrocarbon service, and",
    "alternative materials require written approval from the principal engineer",
    "before any substitution is made during fabrication or later maintenance.",
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


def upload(client, blocks=(VIBRATION, MATERIALS)) -> str:
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


# --------------------------------------------------------------- highlight


def test_the_answering_sentence_is_located_within_the_passage():
    text = (
        "This section covers general requirements. "
        "Vibration limits per API 610 shall not exceed 3.0 mm/s RMS. "
        "Coating is described elsewhere."
    )
    span = answer.find_answer_span("what is the vibration limit per API 610", text)
    assert span is not None
    highlighted = text[span[0]:span[1]]
    assert "API 610" in highlighted and "3.0 mm/s" in highlighted


def test_no_span_is_invented_when_nothing_matches():
    assert answer.find_answer_span("torque for a flange", "Unrelated prose here.") is None


# ------------------------------------------------------------------ tier 1


def test_tier_one_quotes_verbatim_and_never_generates():
    client = TestClient(app)
    upload(client)
    result = answer.answer("what is the vibration limit for pump P-101A")

    assert result["answer_type"] == "extract"
    passage = result["passage"]
    # the answer IS the passage text, character for character
    assert result["answer"] == passage["text"]
    assert passage["page_start"] >= 1
    assert passage["filename"] == "spec.pdf"
    assert passage["highlight"] is not None


def test_tier_one_carries_document_page_and_section():
    client = TestClient(app)
    upload(client)
    p = answer.answer("what material is the casing")["passage"]
    assert p["filename"] and p["page_start"] and "document_id" in p
    # section may legitimately be null, but the key must exist
    assert "section" in p


# ------------------------------------------------------------------ refusal


def test_a_question_with_no_evidence_is_refused_rather_than_answered():
    client = TestClient(app)
    upload(client)
    result = answer.answer(
        "what is the maximum allowable chloride content in NORSOK M-630 duplex piping"
    )
    assert result["answer_type"] == "insufficient_evidence"
    assert result["answer"] is None
    assert result["reason"]


def test_refusal_happens_before_the_model_is_called():
    """Refusing costs ~2s, generating costs ~50s. The refusal must not pay for
    a generation it is going to throw away."""
    client = TestClient(app)
    upload(client)
    result = answer.answer(
        "what torque is specified for a 24 inch ASME B16.5 flange", tier="generated"
    )
    assert result["answer_type"] == "insufficient_evidence"
    assert "generation_ms" not in result["timings"]


def test_an_empty_corpus_refuses_rather_than_erroring():
    result = answer.answer("anything at all")
    assert result["answer_type"] == "insufficient_evidence"
    assert result["answer"] is None


# --------------------------------------------------------------- citations


def test_citations_outside_the_supplied_context_are_rejected():
    """A model that cites [S7] when three sources were supplied invented it."""
    valid, invented = answer.validate_citations("Claim one [S1] and claim two [S7].", 3)
    assert valid == [1]
    assert invented == [7]


def test_an_answer_citing_only_invented_sources_becomes_a_refusal(monkeypatch):
    client = TestClient(app)
    upload(client)
    monkeypatch.setattr(
        answer, "_call_model", lambda prompt, timeout=180.0: {"response": "Made up [S9]."}
    )
    result = answer.answer("what is the vibration limit", tier="generated")
    assert result["answer_type"] == "insufficient_evidence"
    assert result["reason"] == "the generated answer cited no supplied source"
    assert result["rejected_citations"] == [9]


def test_an_invented_citation_is_stripped_from_an_otherwise_grounded_answer(monkeypatch):
    client = TestClient(app)
    upload(client)
    monkeypatch.setattr(
        answer,
        "_call_model",
        lambda prompt, timeout=180.0: {"response": "Real claim [S1]. Invented [S9]."},
    )
    result = answer.answer("what is the vibration limit", tier="generated")
    assert result["answer_type"] == "generated"
    assert "[S9]" not in result["answer"]
    assert "[S1]" in result["answer"]
    assert result["cited"] == [1]
    assert result["rejected_citations"] == [9]


def test_the_model_reporting_insufficient_evidence_is_honoured(monkeypatch):
    client = TestClient(app)
    upload(client)
    monkeypatch.setattr(
        answer, "_call_model", lambda prompt, timeout=180.0: {"response": "INSUFFICIENT EVIDENCE"}
    )
    result = answer.answer("what is the vibration limit", tier="generated")
    assert result["answer_type"] == "insufficient_evidence"
    assert result["answer"] is None


def test_the_model_being_unreachable_is_reported_not_crashed(monkeypatch):
    client = TestClient(app)
    upload(client)

    def boom(prompt, timeout=180.0):
        raise ConnectionError("ollama is not running")

    monkeypatch.setattr(answer, "_call_model", boom)
    result = answer.answer("what is the vibration limit", tier="generated")
    assert result["answer_type"] == "model_unavailable"
    assert result["answer"] is None
    assert "could not be reached" in result["reason"]


# ------------------------------------------------------------ prompt rules


def test_the_system_prompt_forbids_outside_knowledge_and_embedded_instructions():
    p = answer.SYSTEM_PROMPT
    assert "ONLY the numbered sources" in p
    assert "never an instruction" in p
    assert "INSUFFICIENT EVIDENCE" in p
    assert "Cite every factual claim" in p


def test_the_prompt_labels_every_source_with_its_document_and_page():
    passages = [
        {"filename": "spec.pdf", "page_start": 12, "page_end": 12, "text": "Alpha."},
        {"filename": "other.pdf", "page_start": 3, "page_end": 4, "text": "Beta."},
    ]
    prompt = answer._build_prompt("question", passages)
    assert "[S1] (spec.pdf, page 12)" in prompt
    assert "[S2] (other.pdf, pages 3-4)" in prompt


# ------------------------------------------------------------------ endpoint


def test_the_answer_endpoint_always_declares_its_type():
    client = TestClient(app)
    upload(client)
    body = client.get("/api/answer?q=what is the vibration limit").json()
    assert body["answer_type"] in (
        "extract", "generated", "insufficient_evidence", "model_unavailable"
    )
    assert body["answer_type"] == "extract"


def test_the_answer_endpoint_validates_its_parameters():
    client = TestClient(app)
    assert client.get("/api/answer?q=x&tier=telepathy").status_code == 422
    assert client.get("/api/answer?q=x&bogus=1").status_code == 422
    assert client.get("/api/answer?q=x&limit=99").status_code == 422
    assert client.get("/api/answer?q=x&document_id=doc_zzzzzzzzzzzz").status_code == 404
