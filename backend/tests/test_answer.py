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


def test_document_count_is_answered_as_scoped_metadata():
    client = TestClient(app)
    first = upload(client)
    result = answer.answer(
        "how many documents are uploaded?",
        allowed_document_ids=frozenset({first}),
    )
    assert result["answer_type"] == "metadata"
    assert result["answer"] == "There are 1 uploaded document in your accessible corpus."
    assert result["passages"] == []


def test_tier_one_quotes_verbatim_and_never_generates():
    client = TestClient(app)
    upload(client)
    result = answer.answer("what is the vibration limit for pump P-101A", allowed_document_ids=_scope())

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
    p = answer.answer("what material is the casing", allowed_document_ids=_scope())["passage"]
    assert p["filename"] and p["page_start"] and "document_id" in p
    # section may legitimately be null, but the key must exist
    assert "section" in p


# ------------------------------------------------------------------ refusal


def test_a_question_with_no_evidence_is_refused_rather_than_answered():
    client = TestClient(app)
    upload(client)
    result = answer.answer(
        "what is the maximum allowable chloride content in NORSOK M-630 duplex piping"
    ,
        allowed_document_ids=_scope())
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
    ,
        allowed_document_ids=_scope())
    assert result["answer_type"] == "insufficient_evidence"
    assert "generation_ms" not in result["timings"]


def test_written_review_request_can_reach_grounded_model_below_lookup_floor():
    """A broad critique is a synthesis request, not a one-fact lookup."""
    assert answer._is_broad_review_request(
        "DO A CRITEQUE ON MATERIAL AND DOCUMENT",
        {"covered": ["MATERIAL", "DOCUMENT"]},
        "generated",
    ) is True
    assert answer._is_broad_review_request(
        "what is the material limit",
        {"covered": ["MATERIAL", "LIMIT"]},
        "extract",
    ) is False


def test_an_empty_corpus_refuses_rather_than_erroring():
    result = answer.answer("anything at all", allowed_document_ids=_scope())
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
    result = answer.answer("what is the vibration limit", tier="generated", allowed_document_ids=_scope())
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
    result = answer.answer("what is the vibration limit", tier="generated", allowed_document_ids=_scope())
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
    result = answer.answer("what is the vibration limit", tier="generated", allowed_document_ids=_scope())
    assert result["answer_type"] == "insufficient_evidence"
    assert result["answer"] is None


def test_the_model_being_unreachable_is_reported_not_crashed(monkeypatch):
    client = TestClient(app)
    upload(client)

    def boom(prompt, timeout=180.0):
        raise ConnectionError("ollama is not running")

    monkeypatch.setattr(answer, "_call_model", boom)
    result = answer.answer("what is the vibration limit", tier="generated", allowed_document_ids=_scope())
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


# ------------------------------------------------------ question punctuation


def test_trailing_punctuation_is_stripped_before_anything_scores():
    from app.search import normalise_question

    assert normalise_question("what is ndft ??") == "what is ndft"
    assert normalise_question("what is ndft?") == "what is ndft"
    assert normalise_question("  what   is  NDFT  ") == "what is NDFT"
    assert normalise_question("") == ""


def test_case_is_left_alone():
    """The cross-encoder is uncased - measured at 1.437 vs 1.426 for the same
    question either way - and identifiers like CA6NM read better as written."""
    from app.search import normalise_question

    assert normalise_question("what is CA6NM") == "what is CA6NM"


def test_a_trailing_period_does_not_eat_a_clause_number():
    from app.search import normalise_question

    assert normalise_question("what does clause 5.3.2 say") == "what does clause 5.3.2 say"
    assert normalise_question("what does clause 5.3.2. say.") == "what does clause 5.3.2. say"


def test_the_response_shows_the_question_as_typed_not_as_normalised():
    client = TestClient(app)
    upload(client)
    result = answer.answer("what is the vibration limit ??", allowed_document_ids=_scope())
    assert result["question"] == "what is the vibration limit ??"


def test_how_a_question_is_punctuated_does_not_change_whether_it_is_answered():
    """A question mark cost 1.26 rerank points on the NORSOK corpus, and two
    of them pushed a question the document answers below the credibility
    threshold. The reader typed the same question either way."""
    client = TestClient(app)
    upload(client)
    plain = answer.answer("what is the vibration limit for pump P-101A", allowed_document_ids=_scope())
    punctuated = answer.answer("what is the vibration limit for pump P-101A ??", allowed_document_ids=_scope())
    assert plain["answer_type"] == punctuated["answer_type"] == "extract"
    assert plain["passage"]["chunk_id"] == punctuated["passage"]["chunk_id"]


def test_punctuation_stripping_does_not_rescue_an_unanswerable_question():
    """The control. Fixing the input must not have loosened the gate."""
    client = TestClient(app)
    upload(client)
    result = answer.answer(
        "what is the maximum allowable chloride content in NORSOK M-630 duplex piping??"
    ,
        allowed_document_ids=_scope())
    assert result["answer_type"] == "insufficient_evidence"


# ------------------------------------------------------------ small-to-big


def test_a_passage_is_expanded_to_its_parent_block():
    """Retrieval works on the small chunk; the reader is shown the surrounding
    block. NORSOK's A.1 is a thickness table followed by its notes, and
    quoting only one of them answered with the notes and left the figures in
    the chunk next door."""
    client = TestClient(app)
    upload(client)
    result = answer.answer("what is the vibration limit for pump P-101A", allowed_document_ids=_scope())
    p = result["passage"]
    assert p["chunks_joined"] >= 1
    assert p["match_span"] is not None
    start, end = p["match_span"]
    # the chunk that actually matched is still locatable inside the expansion
    assert 0 <= start < end <= len(p["text"])


def test_expansion_never_crosses_into_another_section():
    """A passage labelled A.1 containing A.2's text would be a worse defect
    than the one small-to-big fixes."""
    from app import passages

    client = TestClient(app)
    upload(client)
    conn = db.connect()
    rows = conn.execute(
        "SELECT id, document_id, section FROM chunks WHERE retrievable = 1"
    ).fetchall()
    for r in rows:
        expanded = passages.expand_passage(r["id"], r["document_id"])
        if expanded:
            assert expanded["section"] == r["section"]


def test_the_matched_chunk_is_never_dropped_by_the_budget():
    from app import passages

    client = TestClient(app)
    upload(client)
    conn = db.connect()
    r = conn.execute(
        "SELECT id, document_id, text FROM chunks WHERE retrievable = 1 LIMIT 1"
    ).fetchone()
    # a budget far below one chunk must still return that chunk
    expanded = passages.expand_passage(r["id"], r["document_id"], budget=10)
    assert r["text"] in expanded["text"]
    assert expanded["chunks_joined"] == 1


def test_an_unknown_chunk_expands_to_nothing_rather_than_erroring():
    from app import passages

    assert passages.expand_passage("nope", "doc_nope") == {}


def test_the_generated_tier_uses_a_smaller_budget_so_sources_fit(monkeypatch):
    """Three expanded sources have to fit inside num_ctx alongside the prompt.
    Overflowing it would silently truncate the evidence the answer is supposed
    to be grounded in."""
    client = TestClient(app)
    upload(client)
    seen = {}
    monkeypatch.setattr(
        answer, "_call_model",
        lambda prompt, timeout=180.0: seen.update(prompt=prompt) or {"response": "x [S1]."},
    )
    answer.answer("what is the vibration limit", tier="generated", allowed_document_ids=_scope())
    assert len(seen["prompt"]) <= 3 * settings.generated_context_chars + 800


def _scope():
    """Corpus-wide scope, stated explicitly.

    Retrieval now REQUIRES an access scope with no default, so a test has to
    name the documents it is allowed to see. These tests want all of them, and
    saying so out loud is the point: when authentication arrives, every one of
    these is a line somebody changes on purpose rather than a default that
    quietly kept meaning "everything".
    """
    from app.search import every_document_id
    return every_document_id()


# ------------------------------------------------- truncation is not silent

def test_a_citation_cut_in_half_by_the_budget_is_removed():
    """`[S2` with no closing bracket shows the reader literal broken text and
    reads as a fault in the citation system rather than a length limit. A
    broken citation is worse than a missing one - the same reasoning that
    already strips invented citations."""
    from app.answer import strip_half_citation
    assert strip_half_citation(
        "Trust decisions use external sources to run a trust algorithm [S2"
    ) == "Trust decisions use external sources to run a trust algorithm"
    assert strip_half_citation("...perform containment [S") == "...perform containment"
    assert strip_half_citation("...perform containment [") == "...perform containment"


def test_a_complete_citation_is_never_stripped():
    from app.answer import strip_half_citation
    text = "The policy engine grants access [S2]."
    assert strip_half_citation(text) == text
    # and a bracket mid-sentence is ordinary prose, not a half-citation
    mid = "The array [S1] and later text continues here."
    assert strip_half_citation(mid) == mid


def test_a_truncated_answer_says_it_was_truncated_and_loses_its_half_citation(
        monkeypatch):
    """The reader must be able to tell "the model finished" from "it ran out of
    budget" from "it crashed". Those are three situations and only one is a
    defect; a silent stop makes all three look identical.

    Reproduces the demo defect exactly: generation stopped inside `[S1`.
    """
    from app import answer as answer_mod
    from app.search import every_document_id

    client = TestClient(app)
    doc_id = upload(client)
    IngestionWorker().process(doc_id)

    def fake_model(prompt, timeout=180.0):
        return {
            # The realistic shape of the reported defect: complete citations,
            # then the budget runs out inside the next marker.
            "response": ("Containment isolates affected hosts [S1]. Eradication "
                         "removes the cause [S1"),
            "done_reason": "length",
            "eval_count": 250,
            "prompt_eval_count": 900,
        }

    monkeypatch.setattr(answer_mod, "_call_model", fake_model)
    r = answer_mod.answer("what vibration limits are specified", tier="generated",
                          limit=3, allowed_document_ids=every_document_id())

    assert r["answer_type"] == "generated"
    assert r["truncated"] is True, "a capped generation must say it was capped"
    assert not r["answer"].rstrip().endswith("[S1"), (
        "the half-written citation marker survived into the answer")
    assert r["answer"].rstrip().endswith("removes the cause")
    assert "[S1]." in r["answer"], "the COMPLETE citation must survive"


def test_an_answer_that_finished_is_not_marked_truncated(monkeypatch):
    from app import answer as answer_mod
    from app.search import every_document_id

    client = TestClient(app)
    doc_id = upload(client)
    IngestionWorker().process(doc_id)

    monkeypatch.setattr(answer_mod, "_call_model", lambda prompt, timeout=180.0: {
        "response": "Containment includes isolating affected hosts [S1].",
        "done_reason": "stop", "eval_count": 51, "prompt_eval_count": 900,
    })
    r = answer_mod.answer("what vibration limits are specified", tier="generated",
                          limit=3, allowed_document_ids=every_document_id())
    assert r["truncated"] is False
    assert r["answer"].endswith("[S1].")


def test_stripping_the_only_citation_refuses_and_says_why(monkeypatch):
    """A surprising but correct consequence, asserted so it stays deliberate.

    If the budget ran out inside the ONLY citation, removing it leaves an
    answer with no support - and an uncited generated answer is not shown, by
    the same rule that rejects invented citations. The refusal must say it was
    a length limit rather than a lack of evidence, because those are different
    facts and only one of them is about the documents.
    """
    from app import answer as answer_mod
    from app.search import every_document_id

    client = TestClient(app)
    doc_id = upload(client)
    IngestionWorker().process(doc_id)

    monkeypatch.setattr(answer_mod, "_call_model", lambda prompt, timeout=180.0: {
        "response": "Containment includes isolating affected hosts [S1",
        "done_reason": "length", "eval_count": 250, "prompt_eval_count": 900,
    })
    r = answer_mod.answer("what vibration limits are specified", tier="generated",
                          limit=3, allowed_document_ids=every_document_id())
    assert r["answer_type"] == "insufficient_evidence"
    assert r["truncated"] is True
    assert "length limit" in r["reason"], r["reason"]
