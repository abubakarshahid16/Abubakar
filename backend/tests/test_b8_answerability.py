"""B8: the answer-level safety gate.

Every answer carries a verdict on whether its evidence ANSWERS the question,
decided by structure the code can check - never by the reranker score:
supported / insufficient_evidence / conflicting_evidence / ambiguous_evidence
/ requires_another_document / requires_engineer_review. Synthetic documents
only; each test states the false confidence it prevents. Mutations M818-M824.
"""
from __future__ import annotations

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import answer, answerability, chat, db, keyword
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

VESSELS_A = ["4.2 Design Pressure",
             "The design pressure of every storage vessel shall be 3.5 bar gauge",
             "measured at the top of the shell for the full operating range."]
VESSELS_B = ["4.2 Design Pressure",
             "The design pressure of every storage vessel shall be 5 bar gauge",
             "measured at the top of the shell for the full operating range."]
PUMPS = ["7.1 Pump Selection",
         "Centrifugal pumps for this service shall be in accordance with API 610",
         "and shall be supplied with the vendor data sheet completed in full."]
COATING = ["3.1 Surface Preparation",
           "Surfaces shall be abrasive blast cleaned to a profile of 50 to 75 micrometres",
           "before the first coat of primer is applied to the steel."]


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "b8.sqlite")
    db.reset_connection(); db.init_db(); keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    ids = {}

    def add(name, *blocks):
        path = tmp_path / name
        pdf = pymupdf.open()
        for block in blocks:
            page = pdf.new_page()
            for i, line in enumerate(block):
                page.insert_text((72, 100 + i * 16), line)
        pdf.save(str(path)); pdf.close()
        with open(path, "rb") as fh:
            doc = client.post("/api/documents", files={"file": (name, fh, "application/pdf")}).json()["document"]["id"]
        IngestionWorker().process(doc)
        ids[name] = doc
    add("ABC-V-001.pdf", VESSELS_A, COATING)
    add("XYZ-V-002.pdf", VESSELS_B)
    add("ABC-P-003.pdf", PUMPS)
    yield ids
    db.reset_connection()


def _ask(question, ids, only=None):
    allowed = frozenset(ids[n] for n in (only or ids))
    return answer.answer(question, allowed_document_ids=allowed)


def test_a_clearly_answered_question_is_supported_and_cites_its_passage(library):
    r = _ask("what surface profile is required after abrasive blast cleaning?", library)
    a = r["answerability"]
    assert a["verdict"] == answerability.SUPPORTED
    assert a["evidence"] and a["evidence"][0]["document_id"] == library["ABC-V-001.pdf"]
    assert a["evidence"][0]["page_start"] == 2


def test_a_subject_no_document_mentions_is_insufficient_not_answered(library):
    """False confidence prevented: an Inconel question answered from a
    passage about something else."""
    r = _ask("what is the Inconel cladding thickness for the reactor?", library)
    assert r["answerability"]["verdict"] == answerability.INSUFFICIENT
    assert r["answerability"]["evidence"] == []


def test_a_compliance_judgement_is_routed_to_an_engineer(library):
    """Chat never decides compliance: the documents are shown, the verdict is not."""
    r = _ask("is a design pressure of 4 bar compliant with the vessel standard?", library,
             only=["ABC-V-001.pdf"])
    assert r["answerability"]["verdict"] == answerability.ENGINEER_REVIEW


def test_a_clause_that_defers_to_a_standard_not_held_says_so(library):
    """False confidence prevented: 'API 610' is where the requirement is, and
    no API 610 is among the reader's documents."""
    r = _ask("what requirements apply to the centrifugal pumps for this service?", library,
             only=["ABC-P-003.pdf"])
    a = r["answerability"]
    assert a["verdict"] == answerability.ANOTHER_DOCUMENT
    assert "API 610" in a["reason"]


def test_two_standards_stating_different_values_are_a_conflict(library):
    """False confidence prevented: 3.5 bar in one standard, 5 bar in the other.
    Search drops the second as a near-copy (one token differs); the gate reads
    the dropped copy back and does not pick a side."""
    r = _ask("what is the design pressure of the storage vessels?", library,
             only=["ABC-V-001.pdf", "XYZ-V-002.pdf"])
    a = r["answerability"]
    assert a["verdict"] == answerability.CONFLICTING
    assert {e["document_id"] for e in a["evidence"]} == {library["ABC-V-001.pdf"], library["XYZ-V-002.pdf"]}


def test_one_standard_alone_is_not_a_conflict(library):
    r = _ask("what is the design pressure of the storage vessels?", library, only=["ABC-V-001.pdf"])
    assert r["answerability"]["verdict"] == answerability.SUPPORTED


def test_the_verdict_never_claims_high_confidence(library):
    r = _ask("what surface profile is required after abrasive blast cleaning?", library)
    assert "high" not in str(r["answerability"]).lower()


def test_the_verdict_survives_the_conversation_and_the_api(library):
    convo = chat.create_conversation()
    r = chat.ask(convo["id"], "what is the Inconel cladding thickness for the reactor?",
                 allowed_document_ids=frozenset(library.values()))
    assert r["answerability"]["verdict"] == answerability.INSUFFICIENT
    stored = chat.get_conversation_detail(convo["id"]) if hasattr(chat, "get_conversation_detail") else None
    if stored is not None:
        assert any((m.get("payload") or {}).get("answerability") for m in stored.get("messages", []))


def test_the_reranker_score_takes_no_part():
    import inspect
    assert "rerank" not in inspect.getsource(answerability.assess)


def test_the_verdict_reaches_the_http_response(library):
    """The response model once dropped fields it did not declare - a verdict
    the UI never receives protects no one."""
    client = TestClient(app)
    convo = client.post("/api/conversations", json={}).json()
    cid = convo.get("id") or convo.get("conversation", {}).get("id")
    body = client.post(f"/api/conversations/{cid}/ask",
                       json={"question": "what is the Inconel cladding thickness for the reactor?"}).json()
    assert body["answerability"]["verdict"] == answerability.INSUFFICIENT
    assert "understanding" in body


# ------------------------------------------------------------ the model judge

class _Judge:
    """A fake reasoning model with a scripted reply."""
    def __init__(self, reply=None, raises=None):
        self.reply, self.raises, self.calls = reply, raises, 0

    def reason(self, packet):
        from app.reasoning_provider import Response
        self.calls += 1
        if self.raises:
            raise self.raises
        return Response(text=self.reply, provider="ollama", model_tag="fake", digest="d",
                        finish_reason="stop", prompt_sha256=packet.sha256)


def _judged(library, monkeypatch, fake, question="what surface profile is required after abrasive blast cleaning?"):
    monkeypatch.setattr(answerability, "judge_provider", lambda: fake)
    return _ask(question, library)["answerability"]


def test_the_judge_is_off_by_default():
    assert settings.answer_judge_enabled is False and answerability.judge_provider() is None


def test_a_model_no_downgrades_a_supported_answer(library, monkeypatch):
    fake = _Judge('{"answers": false, "passage": 1, "quote": "", "reason": "topic only"}')
    a = _judged(library, monkeypatch, fake)
    assert fake.calls == 1 and a["verdict"] == answerability.INSUFFICIENT and a["judge"]["accepted"]


def test_a_model_yes_is_accepted_only_with_a_verbatim_quote(library, monkeypatch):
    fake = _Judge('{"answers": true, "passage": 1, "quote": "a profile of 50 to 75 micrometres"}')
    a = _judged(library, monkeypatch, fake)
    assert a["verdict"] == answerability.SUPPORTED and a["judge"]["accepted"]
    assert a["judge"]["quote"] == "a profile of 50 to 75 micrometres"


def test_an_invented_quote_is_rejected_and_changes_nothing(library, monkeypatch):
    """False confidence prevented: a model 'yes' backed by words the passage
    does not contain is not evidence."""
    fake = _Judge('{"answers": true, "passage": 1, "quote": "a profile of 90 micrometres"}')
    a = _judged(library, monkeypatch, fake)
    assert a["judge"]["accepted"] is False and "not verbatim" in a["judge"]["why"]
    assert a["verdict"] == answerability.SUPPORTED   # the structural verdict stands


def test_a_malformed_reply_is_rejected(library, monkeypatch):
    a = _judged(library, monkeypatch, _Judge("I think it probably does."))
    assert a["judge"]["accepted"] is False and "rejected" in a["judge"]["why"]


def test_a_passage_number_that_does_not_exist_is_rejected(library, monkeypatch):
    a = _judged(library, monkeypatch, _Judge('{"answers": true, "passage": 9, "quote": "profile"}'))
    assert a["judge"]["accepted"] is False


def test_the_judge_can_never_turn_a_refusal_into_an_answer(library, monkeypatch):
    fake = _Judge('{"answers": true, "passage": 1, "quote": "storage vessel"}')
    a = _judged(library, monkeypatch, fake, "what is the Inconel cladding thickness for the reactor?")
    assert fake.calls == 0 and a["verdict"] == answerability.INSUFFICIENT


def test_a_failing_model_leaves_the_structural_verdict(library, monkeypatch):
    a = _judged(library, monkeypatch, _Judge(raises=TimeoutError("slow")))
    assert a["verdict"] == answerability.SUPPORTED and a["judge"]["accepted"] is False


def test_text_found_in_several_documents_is_ambiguous_not_supported(library):
    """B6C found the answer's own text in two documents: which one answers is
    not the evidence's call."""
    base = _ask("what surface profile is required after abrasive blast cleaning?", library)
    flagged = {**base, "scope_ambiguity": {"reason": "same text", "documents": [
        {"document_id": library["ABC-V-001.pdf"]}, {"document_id": library["XYZ-V-002.pdf"]}]}}
    verdict = answerability.assess("what surface profile is required after abrasive blast cleaning?",
                                   flagged, allowed_document_ids=frozenset(library.values()))
    assert verdict["verdict"] == answerability.AMBIGUOUS


def test_a_clause_stating_its_own_value_is_not_a_deferral(library):
    """A requirement that states a value and also cites a standard answers
    the question; only a clause that ONLY points elsewhere is flagged."""
    result = {"answer_type": "extract", "passage": {
        "chunk_id": "x", "document_id": library["ABC-P-003.pdf"], "page_start": 1, "page_end": 1,
        "section": "7.1", "text": "Pump baseplates shall be 25 mm thick in accordance with API 610."}}
    v = answerability.assess("how thick shall the pump baseplates be?", result,
                             allowed_document_ids=frozenset(library.values()))
    assert v["verdict"] == answerability.SUPPORTED


def test_a_standard_the_question_names_is_not_a_missing_document(library):
    v = _ask("which pumps shall be in accordance with API 610?", library, only=["ABC-P-003.pdf"])
    assert v["answerability"]["verdict"] != answerability.ANOTHER_DOCUMENT
