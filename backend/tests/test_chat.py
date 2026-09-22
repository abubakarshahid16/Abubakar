"""Chat memory: follow-ups resolve, previous answers are never evidence."""

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import answer as answer_mod
from app import chat, db, keyword
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

SYSTEM_ONE = [
    "A.1 Coating system no. 1",
    "Coating system no. 1 shall have a NDFT nominal dry film thickness of 280 um",
    "applied as three coats over blast cleaned carbon steel in atmospheric",
    "service, and the zinc rich primer shall be in accordance with ISO 12944-5",
    "before any topcoat is applied to the prepared surface of the component.",
]

SYSTEM_FOUR = [
    "A.4 Coating system no. 4",
    "Coating system no. 4 shall have a NDFT nominal dry film thickness of 450 um",
    "applied as two coats over blast cleaned carbon steel for insulated",
    "surfaces operating hot, and the curing time between coats shall follow",
    "the manufacturer written procedure for the product actually supplied.",
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


def upload(client, blocks=(SYSTEM_ONE, SYSTEM_FOUR)) -> str:
    path = settings.data_dir / "spec.pdf"
    doc = pymupdf.open()
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


# ------------------------------------------------------ follow-up detection


def test_a_standalone_question_is_not_treated_as_a_follow_up():
    assert not chat.is_followup("what is the nominal dry film thickness for coating system 1")


def test_an_anaphor_marks_a_follow_up():
    assert chat.is_followup("what is its curing time")
    assert chat.is_followup("how thick is that coat")


def test_a_continuation_opener_marks_a_follow_up():
    assert chat.is_followup("and the roughness requirement")
    assert chat.is_followup("what about the primer")


def test_a_question_too_short_to_carry_a_subject_is_a_follow_up():
    assert chat.is_followup("how thick")


def test_an_empty_question_is_not_a_follow_up():
    assert not chat.is_followup("   ")


# ----------------------------------------------------- follow-up resolution


def test_nothing_is_carried_without_a_previous_question():
    resolved, carried = chat.resolve_followup("what is its curing time", [])
    assert resolved == "what is its curing time"
    assert carried == []


def test_a_standalone_question_is_left_exactly_as_typed():
    resolved, carried = chat.resolve_followup(
        "what is the maximum chloride content permitted before blasting",
        ["what is the NDFT for coating system no. 1"],
    )
    assert resolved == "what is the maximum chloride content permitted before blasting"
    assert carried == []


def test_a_follow_up_inherits_the_designator_from_the_previous_question():
    resolved, carried = chat.resolve_followup(
        "what is its curing time", ["what is the NDFT for coating system no. 1"]
    )
    assert "system 1" in carried
    assert "system 1" in resolved
    assert resolved.startswith("what is its curing time")


def test_a_follow_up_inherits_an_identifier():
    resolved, carried = chat.resolve_followup(
        "and its vibration limit", ["what does API 610 require for pump P-101A"]
    )
    assert "API 610" in carried


def test_a_conflicting_designator_is_never_carried():
    """The whole reason this module is careful. "what about system 4" after a
    question about system 1 must not retrieve system 1 - that is not a missing
    answer, it is a confidently wrong one about a different system."""
    resolved, carried = chat.resolve_followup(
        "what about system 4", ["what is the NDFT for coating system no. 1"]
    )
    assert not any(c.startswith("system") for c in carried)
    assert "system 1" not in resolved
    assert " 1" not in resolved.replace("system 4", "")


def test_a_conflicting_designators_number_does_not_leak_back_as_a_topic_word():
    _, carried = chat.resolve_followup(
        "what about system 4", ["what is the NDFT for coating system no. 1"]
    )
    assert "1" not in carried
    assert "no." not in carried


def test_a_short_follow_up_borrows_the_earlier_topic_words():
    resolved, carried = chat.resolve_followup(
        "what about system 4", ["what is the NDFT for coating system no. 1"]
    )
    assert "ndft" in carried and "coating" in carried
    assert "system 4" in resolved


def test_resolution_looks_no_further_back_than_the_window():
    prior = [
        "what does ASTM A216 require",
        "question two about nothing in particular",
        "question three about nothing in particular",
        "what is the NDFT for coating system no. 1",
    ]
    _, carried = chat.resolve_followup("what is its curing time", prior)
    assert "system 1" in carried
    assert "ASTM A216" not in carried  # four turns back, outside the window


def test_the_nearest_question_wins_when_two_designators_compete():
    prior = [
        "what is the NDFT for coating system no. 7",
        "what is the NDFT for coating system no. 1",
    ]
    _, carried = chat.resolve_followup("what is its curing time", prior)
    assert "system 1" in carried
    assert "system 7" not in carried


# ------------------------------------------------- answers are never evidence


def test_prior_user_questions_exclude_assistant_messages():
    convo = chat.create_conversation()
    conn = db.connect()
    chat._insert_message(conn, convo["id"], role="user", text="a real question about coatings")
    chat._insert_message(
        conn, convo["id"], role="assistant",
        text="FABRICATED the thickness is 9999 um", answer_type="extract",
    )
    assert chat.prior_user_questions(convo["id"]) == ["a real question about coatings"]


def test_a_previous_answer_never_reaches_retrieval(monkeypatch):
    """A fabricated claim planted in an earlier answer must not appear in the
    query, in the retrieved passages, or in the prompt. If it could, one wrong
    answer would become the grounds for the next."""
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()

    conn = db.connect()
    chat._insert_message(conn, convo["id"], role="user", text="what is the NDFT for system 1")
    chat._insert_message(
        conn, convo["id"], role="assistant",
        text="UNOBTAINIUM shall be applied at 9999 um.", answer_type="extract",
    )

    seen = {}
    real_search = answer_mod.search_mod.search

    def spy(question, **kwargs):
        seen["question"] = question
        return real_search(question, **kwargs)

    monkeypatch.setattr(answer_mod.search_mod, "search", spy)
    body = client.post(
        f"/api/conversations/{convo['id']}/ask", json={"question": "what is its curing time"}
    ).json()

    assert "UNOBTAINIUM" not in seen["question"]
    assert "9999" not in seen["question"]
    for p in body.get("passages", []) + ([body["passage"]] if body.get("passage") else []):
        assert "UNOBTAINIUM" not in p["text"]


def test_the_generated_prompt_contains_only_retrieved_passages(monkeypatch):
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()
    conn = db.connect()
    chat._insert_message(conn, convo["id"], role="user", text="what is the NDFT for system 1")
    chat._insert_message(
        conn, convo["id"], role="assistant",
        text="UNOBTAINIUM shall be applied at 9999 um.", answer_type="extract",
    )

    prompts = []

    def fake_model(prompt, timeout=180.0):
        prompts.append(prompt)
        return {"response": "The thickness is 280 um [S1]."}

    monkeypatch.setattr(answer_mod, "_call_model", fake_model)
    # a follow-up that actually retrieves, so the model is genuinely reached -
    # asking about curing time here would be refused before generation, and
    # the test would pass without ever inspecting a prompt
    client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={"question": "what is its dry film thickness", "tier": "generated"},
    )
    assert prompts, "the model was never called"
    assert "UNOBTAINIUM" not in prompts[0]
    assert "9999" not in prompts[0]


# ------------------------------------------------------------- conversations


def test_a_conversation_is_titled_from_its_first_question():
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()
    assert convo["title"] == "New conversation"
    client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={"question": "what is the NDFT for coating system no. 1"},
    )
    reopened = client.get(f"/api/conversations/{convo['id']}").json()["conversation"]
    assert reopened["title"] == "what is the NDFT for coating system no. 1"


def test_asking_stores_both_turns_and_advances_the_count():
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()
    client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={"question": "what is the NDFT for coating system no. 1"},
    )
    detail = client.get(f"/api/conversations/{convo['id']}").json()
    roles = [m["role"] for m in detail["messages"]]
    assert roles == ["user", "assistant"]
    assert detail["conversation"]["message_count"] == 2
    assert [m["ordinal"] for m in detail["messages"]] == [1, 2]


def test_what_was_carried_is_recorded_on_the_user_turn():
    """The reader must be able to see what the system assumed, rather than
    having their question silently rewritten underneath them."""
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()
    client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={"question": "what is the NDFT for coating system no. 1"},
    )
    body = client.post(
        f"/api/conversations/{convo['id']}/ask", json={"question": "what is its curing time"}
    ).json()
    assert "system 1" in body["carried_terms"]
    assert body["question"] == "what is its curing time"          # what was typed
    assert body["resolved_question"] != body["question"]          # what was run
    assert "system 1" in body["resolved_question"]

    stored = client.get(f"/api/conversations/{convo['id']}").json()["messages"]
    user_turn = [m for m in stored if m["role"] == "user"][-1]
    assert user_turn["text"] == "what is its curing time"
    assert "system 1" in user_turn["carried_terms"]


def test_a_reopened_conversation_still_carries_its_citations():
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()
    client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={"question": "what is the NDFT for coating system no. 1"},
    )
    messages = client.get(f"/api/conversations/{convo['id']}").json()["messages"]
    assistant = messages[-1]
    assert assistant["answer_type"] == "extract"
    passage = assistant["payload"]["passage"]
    assert passage["filename"] == "spec.pdf"
    assert passage["page_start"] >= 1
    assert passage["text"]


@pytest.mark.parametrize("truncated", [True, False])
def test_a_reopened_conversation_preserves_whether_the_answer_was_truncated(
    monkeypatch, truncated,
):
    """Generation -> real chat write -> database read -> API response.

    The payload is the frontend contract. Existing rows without this optional
    key remain readable because the client defaults an absent value to false.
    """
    def generated(*args, **kwargs):
        return {
            "question": args[0],
            "answer_type": "generated",
            "answer": "A deliberately bounded generated answer [S1].",
            "reason": None,
            "passage": None,
            "answer_passages": [],
            "supporting": [],
            "lexical": None,
            "passages": [],
            "cited": [],
            "rejected_citations": [],
            "truncated": truncated,
            "input_kind": None,
            "evidence_removed": [],
            "coverage": None,
            "examples": [],
            "corpus": None,
            "counts_bounded": 0,
            "retrieval_mode": "hybrid",
            "reranked": False,
            "candidates_considered": 0,
            "model": "deterministic-test-model",
            "prompt_tokens": 8,
            "output_tokens": 8,
            "seconds": 0.01,
            "timings": {},
        }

    monkeypatch.setattr(answer_mod, "answer", generated)
    client = TestClient(app)
    conversation = client.post("/api/conversations").json()

    live = client.post(
        f"/api/conversations/{conversation['id']}/ask",
        json={"question": "generate a deliberately bounded answer", "tier": "generated"},
    )
    assert live.status_code == 200

    replay = client.get(f"/api/conversations/{conversation['id']}")
    assert replay.status_code == 200
    assistant = replay.json()["messages"][-1]
    assert assistant["payload"]["truncated"] is truncated


def test_a_refusal_is_stored_as_a_refusal_not_as_an_answer():
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()
    body = client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={"question": "what torque is specified for a 24 inch ASME B16.5 flange"},
    ).json()
    assert body["answer_type"] == "insufficient_evidence"
    assistant = client.get(f"/api/conversations/{convo['id']}").json()["messages"][-1]
    assert assistant["answer_type"] == "insufficient_evidence"
    assert assistant["text"] is None
    assert assistant["reason"]


def test_conversations_are_listed_most_recently_used_first():
    client = TestClient(app)
    upload(client)
    first = client.post("/api/conversations").json()
    second = client.post("/api/conversations").json()
    client.post(f"/api/conversations/{first['id']}/ask", json={"question": "what is the NDFT"})
    listed = client.get("/api/conversations").json()
    assert listed["total"] == 2
    assert listed["conversations"][0]["id"] == first["id"]
    assert listed["conversations"][0]["first_question"] == "what is the NDFT"
    assert listed["conversations"][1]["id"] == second["id"]


def test_deleting_a_conversation_requires_confirmation():
    client = TestClient(app)
    convo = client.post("/api/conversations").json()
    assert client.delete(f"/api/conversations/{convo['id']}").status_code == 400
    assert client.delete(f"/api/conversations/{convo['id']}?confirm=true").status_code == 200
    assert client.get(f"/api/conversations/{convo['id']}").status_code == 404


def test_deleting_a_conversation_removes_its_messages():
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()
    client.post(f"/api/conversations/{convo['id']}/ask", json={"question": "what is the NDFT"})
    client.delete(f"/api/conversations/{convo['id']}?confirm=true")
    left = db.connect().execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (convo["id"],)
    ).fetchone()[0]
    assert left == 0


# ------------------------------------------------------------------ explain


def test_explain_upgrades_an_answer_without_duplicating_the_question(monkeypatch):
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()
    first = client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={"question": "what is the NDFT for coating system no. 1"},
    ).json()
    assert first["answer_type"] == "extract"

    monkeypatch.setattr(
        answer_mod, "_call_model",
        lambda prompt, timeout=180.0: {"response": "It is 280 um [S1]."},
    )
    body = client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={
            "tier": "generated",
            "explain_of": first["assistant_message"]["id"],
        },
    ).json()

    assert body["answer_type"] == "generated"
    messages = client.get(f"/api/conversations/{convo['id']}").json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "assistant"]
    assert messages[-1]["explains_id"] == first["assistant_message"]["id"]


def test_explain_reuses_the_resolved_question_rather_than_resolving_again():
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()
    client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={"question": "what is the NDFT for coating system no. 1"},
    )
    follow = client.post(
        f"/api/conversations/{convo['id']}/ask", json={"question": "what is its curing time"}
    ).json()

    body = client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={"tier": "extract", "explain_of": follow["assistant_message"]["id"]},
    ).json()
    assert body["resolved_question"] == follow["resolved_question"]
    assert "system 1" in body["resolved_question"]


def test_explaining_an_unknown_message_is_a_404():
    client = TestClient(app)
    convo = client.post("/api/conversations").json()
    r = client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={"tier": "generated", "explain_of": "msg_doesnotexist"},
    )
    assert r.status_code == 404


# --------------------------------------------------------------- validation


def test_the_ask_endpoint_validates_its_body():
    client = TestClient(app)
    convo = client.post("/api/conversations").json()
    cid = convo["id"]
    assert client.post(f"/api/conversations/{cid}/ask", json={"question": "x", "bogus": 1}).status_code == 422
    assert client.post(f"/api/conversations/{cid}/ask", json={"question": "x", "tier": "telepathy"}).status_code == 422
    assert client.post(f"/api/conversations/{cid}/ask", json={"question": "x", "limit": 99}).status_code == 422
    # An empty question is not a client error - it is somebody pressing enter.
    # It classifies as "empty" and gets the guidance reply. See test_intent.
    blank = client.post(f"/api/conversations/{cid}/ask", json={"question": "   "})
    assert blank.status_code == 200
    assert blank.json()["answer_type"] == "guidance"


def test_an_unknown_conversation_is_a_404_everywhere():
    client = TestClient(app)
    assert client.get("/api/conversations/conv_nope").status_code == 404
    assert client.delete("/api/conversations/conv_nope?confirm=true").status_code == 404
    assert client.post(
        "/api/conversations/conv_nope/ask", json={"question": "x"}
    ).status_code == 404


def test_a_conversation_scoped_to_a_document_confines_its_answers():
    client = TestClient(app)
    doc_id = upload(client)
    convo = client.post("/api/conversations", json={"document_id": doc_id}).json()
    assert convo["document_id"] == doc_id
    body = client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={"question": "what is the NDFT for coating system no. 1"},
    ).json()
    assert body["passage"]["document_id"] == doc_id


def test_a_conversation_cannot_be_scoped_to_an_unknown_document():
    client = TestClient(app)
    r = client.post("/api/conversations", json={"document_id": "doc_zzzzzzzzzzzz"})
    assert r.status_code == 404


# ------------------------------------------- the completeness gate (rule: carry
# on grammatical dependence, never on word count)

def test_a_complete_short_question_does_not_borrow_anyone_elses_subject():
    """The defect this gate exists for.

    "what is the warranty period" is complete and self-contained. It has two
    content words, and the old gate - len(_content_words) < 3 - called it a
    follow-up for that reason alone, so it inherited terms from whatever
    happened to be asked before it.

    Measured over 200 shuffled orderings of the eval set, that single
    misclassification made 72 of them (36%) answer confidently where a refusal
    was correct. It was the ONLY failure in any ordering.
    """
    prior = [
        "what is the MDFT and number of coats for coating system no. 9",
        "what is the soluble impurity limit in clause 6.3",
    ]
    resolved, carried = chat.resolve_followup("what is the warranty period", prior)
    assert carried == [], f"borrowed {carried} into a self-contained question"
    assert resolved == "what is the warranty period"


def test_a_grammatically_incomplete_question_still_borrows():
    """The feature must survive the fix. A bare noun phrase genuinely depends
    on the previous turn, and these two cases are the entire justification for
    term-carrying existing - both were measured to ANSWER only when carrying."""
    resolved, carried = chat.resolve_followup(
        "and the minimum",
        ["what is the maximum operating temperature for zinc metal spray"],
    )
    assert carried, "a bare continuation must still inherit its subject"
    assert "zinc" in resolved.lower()

    resolved, carried = chat.resolve_followup(
        "when is it required", ["how is the stripe coat applied"])
    assert carried, "a question with an unresolved pronoun must still inherit"
    assert "stripe" in resolved.lower()


def test_completeness_is_judged_on_a_finite_verb_not_on_length():
    assert chat.is_complete_question("what is the warranty period")
    assert chat.is_complete_question("what does NDFT stand for")
    # bare noun phrases - no finite verb, cannot stand alone
    assert not chat.is_complete_question("system 4?")
    assert not chat.is_complete_question("the minimum")
    # and the follow-up verdict follows from it
    assert not chat.is_followup("what is the warranty period")
    assert chat.is_followup("system 4?")


def test_a_substantial_noun_phrase_is_not_rewritten_as_a_follow_up():
    resolved, carried = chat.resolve_followup(
        "inherent problems of P&IDs",
        ["what is the coating system no. 1 operating temperature"],
    )
    assert resolved == "inherent problems of P&IDs"
    assert carried == []
