"""What the reader typed is classified BEFORE anything is searched.

Typing "hi" used to search the corpus, refuse, and offer three unrelated
passages. Almost everyone opens with a greeting, so that was the first five
seconds of the product for most people who would ever see it.
"""

import fitz
import pytest
from fastapi.testclient import TestClient

from app import chat, db, intent, keyword
from app import search as search_mod
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


# ------------------------------------------------------------ classification


@pytest.mark.parametrize(
    "text",
    ["hi", "Hi", "hello", "Hello!", "hey", "  hey  ", "good morning", "hi there"],
)
def test_a_greeting_is_a_greeting(text):
    assert intent.classify(text) == "greeting"


@pytest.mark.parametrize("text", ["thanks", "Thank you", "thx", "cheers"])
def test_thanks_is_recognised(text):
    assert intent.classify(text) == "thanks"


@pytest.mark.parametrize("text", ["ok", "okay", "sure", "yes", "cool", "got it"])
def test_an_acknowledgement_is_recognised(text):
    assert intent.classify(text) == "acknowledgement"


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_empty_input_is_empty(text):
    assert intent.classify(text) == "empty"


@pytest.mark.parametrize("text", ["???", "!!!", "...", "-"])
def test_punctuation_alone_is_not_a_question(text):
    assert intent.classify(text) == "not_a_question"


def test_a_single_ordinary_word_is_not_a_question():
    assert intent.classify("coating") == "not_a_question"
    assert intent.classify("thickness") == "not_a_question"


def test_a_single_identifier_IS_a_question():
    """The one deliberate departure from "a bare word is not a question".
    Someone typing NDFT or P-101A is looking something up, and sending them a
    greeting instead would be the same discourtesy in the other direction."""
    assert intent.classify("NDFT") == intent.DOCUMENT_QUESTION
    assert intent.classify("P-101A") == intent.DOCUMENT_QUESTION
    assert intent.classify("CA6NM") == intent.DOCUMENT_QUESTION
    assert intent.classify("5.3.2") == intent.DOCUMENT_QUESTION


def test_questions_about_the_assistant_are_not_searched():
    assert intent.classify("what can you do") == "about_the_assistant"
    assert intent.classify("who are you") == "about_the_assistant"
    assert intent.classify("help") == "about_the_assistant"


@pytest.mark.parametrize(
    "text",
    [
        "what is the NDFT for coating system no. 1",
        "hi-lo alarm setpoint for the separator",
        "what does clause 5.3.2 require",
        "is a zinc rich primer required",
    ],
)
def test_a_real_question_is_never_classified_away(text):
    """Over-classifying is the worse failure: refusing to search a genuine
    question because it looked chatty."""
    assert intent.classify(text) == intent.DOCUMENT_QUESTION


# --------------------------------------------------------- the answer itself


@pytest.mark.parametrize("text", ["hi", "hello", "thanks", "ok", "", "coating"])
def test_a_non_question_gets_guidance_and_no_search_results(text):
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()
    body = client.post(
        f"/api/conversations/{convo['id']}/ask", json={"question": text}
    ).json()

    assert body["answer_type"] == "guidance"
    assert body["answer"]
    # nothing was searched, so there is nothing to show as considered
    assert body["passages"] == []
    assert body["passage"] is None
    assert body["retrieval_mode"] == "not_searched"
    assert body["candidates_considered"] == 0
    assert body["reason"] is None


def test_guidance_never_reaches_retrieval_at_all(monkeypatch):
    """Not merely "returns no passages" - the search must not run. A refusal
    costs a rerank; a greeting should cost nothing."""
    from app import answer as answer_mod

    called = []
    monkeypatch.setattr(
        answer_mod.search_mod, "search", lambda *a, **k: called.append(1) or {}
    )
    result = answer_mod.answer("hi", allowed_document_ids=_scope())
    assert result["answer_type"] == "guidance"
    assert called == []


def test_the_examples_are_real_questions_from_the_loaded_documents():
    client = TestClient(app)
    upload(client)
    body = client.post(
        f"/api/conversations/{client.post('/api/conversations').json()['id']}/ask",
        json={"question": "hi"},
    ).json()

    assert body["examples"], "a greeting with no examples is a wasted first impression"
    for example in body["examples"]:
        assert "spec.pdf" in example
    # and they appear in the reply text too, for a caller that reads only `answer`
    assert body["examples"][0] in body["answer"]


def test_the_examples_are_answerable():
    """Suggesting a question the corpus cannot answer would be worse than
    suggesting nothing."""
    client = TestClient(app)
    upload(client)
    examples = intent.example_questions()
    assert examples
    for question in examples:
        from app import answer as answer_mod

        assert answer_mod.answer(question, allowed_document_ids=_scope())["answer_type"] == "extract"


def test_an_empty_corpus_offers_no_examples_rather_than_inventing_them():
    assert intent.example_questions() == []
    from app import answer as answer_mod

    result = answer_mod.answer("hi", allowed_document_ids=_scope())
    assert result["answer_type"] == "guidance"
    assert result["examples"] == []
    assert result["answer"]


def test_the_input_kind_is_reported_so_the_ui_can_explain_itself():
    client = TestClient(app)
    convo = client.post("/api/conversations").json()
    for text, kind in [("hi", "greeting"), ("thanks", "thanks"), ("", "empty")]:
        body = client.post(
            f"/api/conversations/{convo['id']}/ask", json={"question": text}
        ).json()
        assert body["input_kind"] == kind


# ------------------------------------------------------ interaction with chat


def test_a_greeting_never_inherits_a_previous_questions_subject():
    """"hi" is short enough to look like a follow-up. Carrying "system 1" into
    it would search the corpus for something the reader never asked about."""
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()
    client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={"question": "what is the NDFT for coating system no. 1"},
    )
    body = client.post(
        f"/api/conversations/{convo['id']}/ask", json={"question": "hi"}
    ).json()

    assert body["answer_type"] == "guidance"
    assert body["carried_terms"] == []
    assert body["resolved_question"] == "hi"


def test_resolve_followup_leaves_a_greeting_alone():
    resolved, carried = chat.resolve_followup(
        "hi", ["what is the NDFT for coating system no. 1"]
    )
    assert resolved == "hi"
    assert carried == []


def test_a_guidance_turn_is_stored_like_any_other():
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()
    client.post(f"/api/conversations/{convo['id']}/ask", json={"question": "hi"})
    messages = client.get(f"/api/conversations/{convo['id']}").json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[-1]["answer_type"] == "guidance"
    assert messages[-1]["payload"]["examples"] is not None


# ------------------------------------------------- definitional ranking rule


def test_a_definitional_question_is_recognised():
    assert search_mod.definitional_term("what is ndft") == "ndft"
    assert search_mod.definitional_term("what does NDFT mean") == "NDFT"
    assert search_mod.definitional_term("what does NDFT stand for") == "NDFT"
    assert search_mod.definitional_term("define NDFT") == "NDFT"
    assert search_mod.definitional_term("definition of MDFT") == "MDFT"


def test_a_question_asking_for_a_VALUE_is_not_definitional():
    """"what is the NDFT for coating system no. 1" asks what the number is,
    not what the letters mean. It must keep answering from A.1."""
    assert search_mod.definitional_term("what is the NDFT for coating system no. 1") is None
    assert search_mod.definitional_term("what is the vibration limit for pump P-101A") is None


def test_a_definitional_question_cites_the_section_that_defines_the_term():
    client = TestClient(app)
    upload(client)
    from app import answer as answer_mod

    for question in ["what is ndft", "what does NDFT mean", "define NDFT"]:
        result = answer_mod.answer(question, allowed_document_ids=_scope())
        assert result["answer_type"] == "extract", question
        assert result["passage"]["section"] == "3.2 Abbreviations", question


def test_the_value_question_still_cites_the_clause_not_the_glossary():
    client = TestClient(app)
    upload(client)
    from app import answer as answer_mod

    result = answer_mod.answer("what is the NDFT for coating system no. 1", allowed_document_ids=_scope())
    assert result["passage"]["section"].startswith("A.1")


def test_promotion_cannot_rescue_a_term_the_glossary_does_not_define():
    """The rule requires the passage to actually contain the term. A glossary
    that does not define it is not an answer about it."""
    client = TestClient(app)
    upload(client)
    from app import answer as answer_mod

    result = answer_mod.answer("what is XYZQ", allowed_document_ids=_scope())
    assert result["answer_type"] == "insufficient_evidence"


def test_a_greeting_never_becomes_context_for_a_later_question():
    """Guidance turns belong in the transcript but are not questions. Typing
    "hi", "thanks", then "what is ndft" searched for "what is ndft hi thanks"
    and refused a question the document answers."""
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()
    for opener in ("hi", "thanks"):
        client.post(f"/api/conversations/{convo['id']}/ask", json={"question": opener})

    body = client.post(
        f"/api/conversations/{convo['id']}/ask", json={"question": "what is ndft"}
    ).json()
    assert body["carried_terms"] == []
    assert body["resolved_question"] == "what is ndft"
    assert body["answer_type"] == "extract"
    assert body["passage"]["section"] == "3.2 Abbreviations"


def test_a_greeting_between_two_real_questions_does_not_break_the_follow_up():
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()
    client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={"question": "what is the NDFT for coating system no. 1"},
    )
    client.post(f"/api/conversations/{convo['id']}/ask", json={"question": "thanks"})
    body = client.post(
        f"/api/conversations/{convo['id']}/ask", json={"question": "what is its curing time"}
    ).json()
    # the real question is still reachable past the greeting
    assert "system 1" in body["carried_terms"]
    assert "thanks" not in body["carried_terms"]


def test_a_single_term_definitional_lookup_is_not_a_follow_up():
    """"what is ndft" asks what the letters mean. Carrying "system 4" in from
    the previous turn turns it into a different question, and asked third in a
    conversation it answered from A.4 instead of the abbreviations clause."""
    prior = ["what is the NDFT for coating system no. 1", "what about system 4"]
    assert chat.resolve_followup("what is ndft", prior) == ("what is ndft", [])
    assert chat.resolve_followup("define MDFT", prior) == ("define MDFT", [])


def test_a_multi_word_question_still_inherits_its_subject():
    """The exemption is narrow on purpose. "what is its curing time" genuinely
    does depend on what came before, and so does "what is the vibration limit"."""
    prior = ["what is the NDFT for coating system no. 1"]
    _, carried = chat.resolve_followup("what is its curing time", prior)
    assert "system 1" in carried


def test_the_definitional_answer_survives_a_conversation():
    """The acceptance case, in sequence, which is how it broke."""
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()
    for q in ["what is the NDFT for coating system no. 1", "what about system 1"]:
        client.post(f"/api/conversations/{convo['id']}/ask", json={"question": q})
    body = client.post(
        f"/api/conversations/{convo['id']}/ask", json={"question": "what is ndft"}
    ).json()
    assert body["carried_terms"] == []
    assert body["passage"]["section"] == "3.2 Abbreviations"


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
