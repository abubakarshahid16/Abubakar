"""Chat redesign PR 5 (owner order 2026-09-26): what a reader does WITH an answer.

  * "Was this right?" is the reader's own, replaceable, and shown back to them
    - and to nobody else - when the chat is reopened.
  * "Add to comment sheet" files the text the engineer had in front of them
    as a finding on the SUBMITTAL the answer drew on, in its latest review
    run, confirmed by them (so a re-run cannot erase it), and it prints on the
    comment sheet under their name - never "AI Review".
  * The model never files anything: a drafted comment writes nothing until a
    person presses the button.
  * Undo withdraws it - only the filer, only inside the window, only while
    nobody has changed the finding.
  * "@ a document" narrows what is searched; it never widens it.

Synthetic documents only; the model is faked at the transport.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import answer as answer_mod
from app import chat, chat_actions, crs_mapping, db, review, submittal_review
from app.main import app
from tests.test_chat import temp_storage, upload  # noqa: F401 - the fixture is autouse
from tests.test_chat_pr2_router import _ask, _findings, _local_model


def _role(client, document_id: str, role: str) -> None:
    r = client.post("/api/documents/bulk/role",
                    json={"document_ids": [document_id], "document_role": role})
    assert r.status_code in (200, 207), r.text


def _draft(conversation_id: str, source_ids: list[str],
           text: str = "Please state the hydrotest water chloride limit.") -> str:
    """A drafted-comment answer, as `chat_presentation.draft` stores it."""
    conn = db.connect()
    chat._insert_message(conn, conversation_id, role="user", text="write that as a comment",
                         resolved_question="write that as a comment", carried_terms=[])
    message = chat._insert_message(
        conn, conversation_id, role="assistant", text=text, answer_type="general",
        payload={"draft": {"type": "comment", "text": text, "status": "draft",
                           "source_ids": source_ids}, "answer_kind": "action"})
    return message["id"]


@pytest.fixture
def setup():
    client = TestClient(app)
    submittal = upload(client)
    _role(client, submittal, "CONTRACTOR_SUBMITTAL")
    convo = client.post("/api/conversations").json()["id"]
    run = submittal_review.create_review_run(
        submittal_document_id=submittal,
        allowed_document_ids=frozenset({submittal}))
    return client, convo, submittal, run


def _file(client, convo, message_id, text="Please state the chloride limit, and the drain-and-dry method."):
    return client.post(f"/api/conversations/{convo}/messages/{message_id}/comment", json={"text": text})


# ----------------------------------------------------------------- filing

def test_a_drafted_comment_is_filed_only_when_the_engineer_presses_the_button(setup):
    client, convo, submittal, run = setup
    before = _findings()
    message = _draft(convo, [submittal])
    assert _findings() == before, "a draft wrote a finding before anyone filed it"

    r = _file(client, convo, message, text="Edited by the engineer: state the chloride limit.")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["document_id"] == submittal
    assert body["review_run_id"] == run
    finding = review.get(body["finding_id"])
    # the words the engineer had in front of them, not the model's draft
    assert finding["finding"] == "Edited by the engineer: state the chloride limit."
    assert finding["review_run_id"] == run
    assert finding["origin"] == "chat"
    assert finding["approval_status"] == "pending"


def test_a_filed_comment_is_confirmed_by_its_filer_so_a_rerun_cannot_erase_it(setup):
    client, convo, submittal, run = setup
    finding_id = _file(client, convo, _draft(convo, [submittal])).json()["finding_id"]
    assert review.get(finding_id)["confirmed_by"] is not None
    # the comparison's own re-run delete (comparison.run_comparison, replace=True)
    conn = db.connect()
    with conn:
        conn.execute("DELETE FROM review_findings WHERE review_run_id = ? AND confirmed_by IS NULL", (run,))
    assert review.get(finding_id) is not None


def test_it_prints_on_the_comment_sheet_under_the_engineers_name_not_ai_review(setup):
    client, convo, submittal, run = setup
    finding_id = _file(client, convo, _draft(convo, [submittal]), text="State the chloride limit.").json()["finding_id"]
    findings = submittal_review.list_run_findings(run, allowed_document_ids=frozenset({submittal}))
    rows = crs_mapping.build_crs_rows(findings, [], "Sample datasheet")
    mine = [r for r in rows if r["finding_id"] == finding_id]
    assert len(mine) == 1
    assert mine[0]["comment"] == "State the chloride limit."
    assert mine[0]["row_kind"] == crs_mapping.ROW_KIND_ENGINEER_COMMENT
    assert "AI Review" not in mine[0]["comment_by"]
    assert "filed from chat" in mine[0]["comment_by"]


def test_the_submittal_is_chosen_over_a_standard_among_the_sources(setup):
    client, convo, submittal, run = setup
    standard = upload(client, blocks=(["Hydrotest water shall meet the chloride limit."],))
    _role(client, standard, "COMPANY_STANDARD")
    body = _file(client, convo, _draft(convo, [standard, submittal])).json()
    assert body["document_id"] == submittal


def test_an_answer_that_is_not_a_draft_cannot_be_filed(setup):
    client, convo, submittal, run = setup
    conn = db.connect()
    message = chat._insert_message(conn, convo, role="assistant", text="An answer.",
                                   answer_type="general", payload={})
    r = _file(client, convo, message["id"])
    assert r.status_code == 409
    assert _findings() == 0


def test_a_draft_naming_no_readable_document_is_not_filed_anywhere(setup):
    client, convo, submittal, run = setup
    r = _file(client, convo, _draft(convo, ["doc_nobody_can_read"]))
    assert r.status_code == 409
    assert "no document" in r.json()["detail"]["message"]
    assert _findings() == 0


def test_a_document_without_a_review_run_gets_the_finding_but_no_sheet(setup):
    client, convo, submittal, run = setup
    other = upload(client, blocks=(["A second submittal with no review yet."],))
    body = _file(client, convo, _draft(convo, [other])).json()
    assert body["review_run_id"] is None
    assert review.get(body["finding_id"])["document_id"] == other


def test_reopening_the_chat_shows_what_was_filed(setup):
    client, convo, submittal, run = setup
    message = _draft(convo, [submittal])
    finding_id = _file(client, convo, message).json()["finding_id"]
    messages = client.get(f"/api/conversations/{convo}").json()["messages"]
    shown = next(m for m in messages if m["id"] == message)
    assert shown["filed_comment"]["finding_id"] == finding_id


# ------------------------------------------------------------------- undo

def test_undo_withdraws_the_comment_from_the_sheet(setup):
    client, convo, submittal, run = setup
    message = _draft(convo, [submittal])
    finding_id = _file(client, convo, message).json()["finding_id"]
    r = client.delete(f"/api/conversations/{convo}/messages/{message}/comment/{finding_id}")
    assert r.status_code == 200, r.text
    assert review.get(finding_id) is None
    findings = submittal_review.list_run_findings(run, allowed_document_ids=frozenset({submittal}))
    assert all(f["id"] != finding_id for f in findings)
    link = db.connect().execute(
        "SELECT withdrawn_at FROM chat_filed_comments WHERE finding_id = ?", (finding_id,)).fetchone()
    assert link["withdrawn_at"], "the record that it was filed and withdrawn was lost"
    shown = next(m for m in client.get(f"/api/conversations/{convo}").json()["messages"] if m["id"] == message)
    assert shown.get("filed_comment") is None


def test_undo_closes_after_the_window(setup, monkeypatch):
    client, convo, submittal, run = setup
    message = _draft(convo, [submittal])
    finding_id = _file(client, convo, message).json()["finding_id"]
    monkeypatch.setattr(chat_actions, "UNDO_SECONDS", -1)
    r = client.delete(f"/api/conversations/{convo}/messages/{message}/comment/{finding_id}")
    assert r.status_code == 409
    assert review.get(finding_id) is not None


def test_undo_closes_once_anyone_has_changed_the_finding(setup):
    client, convo, submittal, run = setup
    message = _draft(convo, [submittal])
    finding_id = _file(client, convo, message).json()["finding_id"]
    review.update(finding_id, {"severity": "major"}, actor_user_id="someone_else")
    r = client.delete(f"/api/conversations/{convo}/messages/{message}/comment/{finding_id}")
    assert r.status_code == 409
    assert review.get(finding_id)["severity"] == "major"


def test_only_the_filer_can_undo(setup):
    client, convo, submittal, run = setup
    message = _draft(convo, [submittal])
    filed = chat_actions.file_comment(convo, message, text="State the chloride limit.",
                                      user_id="user_a", allowed_document_ids=frozenset({submittal}))
    with pytest.raises(chat_actions.UndoClosed):
        chat_actions.withdraw_comment(convo, message, filed["finding_id"], user_id="user_b")
    assert review.get(filed["finding_id"]) is not None
    # and the filer still can
    chat_actions.withdraw_comment(convo, message, filed["finding_id"], user_id="user_a")
    assert review.get(filed["finding_id"]) is None


# --------------------------------------------------------------- feedback

def test_was_this_right_is_stored_replaced_and_shown_back(setup):
    client, convo, submittal, run = setup
    message = _draft(convo, [submittal])
    url = f"/api/conversations/{convo}/messages/{message}/feedback"
    assert client.post(url, json={"helpful": False, "note": "wrong clause"}).status_code == 200
    assert client.post(url, json={"helpful": True}).status_code == 200
    rows = db.connect().execute("SELECT helpful FROM chat_feedback WHERE message_id = ?", (message,)).fetchall()
    assert [r["helpful"] for r in rows] == [1], "a change of mind must replace, not add"
    shown = next(m for m in client.get(f"/api/conversations/{convo}").json()["messages"] if m["id"] == message)
    assert shown["feedback"] is True


def test_feedback_is_shown_only_to_the_reader_who_gave_it(setup):
    client, convo, submittal, run = setup
    message = _draft(convo, [submittal])
    chat_actions.set_feedback(convo, message, user_key="someone_else", helpful=False)
    shown = next(m for m in chat.get_messages(convo, allowed_document_ids=frozenset({submittal}),
                                             user_key="") if m["id"] == message)
    assert shown.get("feedback") is None


def test_feedback_on_a_question_rather_than_an_answer_is_refused(setup):
    client, convo, submittal, run = setup
    conn = db.connect()
    question = chat._insert_message(conn, convo, role="user", text="q", resolved_question="q", carried_terms=[])
    r = client.post(f"/api/conversations/{convo}/messages/{question['id']}/feedback", json={"helpful": True})
    assert r.status_code == 404


# -------------------------------------------------------- @ a document

def test_picking_documents_narrows_what_is_searched(monkeypatch):
    client = TestClient(app)
    first = upload(client)
    second = upload(client, blocks=(["Pump seal plan 53B is required for this service."],))
    convo = client.post("/api/conversations").json()["id"]
    seen = []
    real = answer_mod.answer

    def spy(*a, **k):
        seen.append(k["allowed_document_ids"])
        return real(*a, **k)

    monkeypatch.setattr(answer_mod, "answer", spy)
    _ask(client, convo, "what is the dry film thickness", document_ids=[second])
    assert seen and seen[-1] == frozenset({second})
    assert first not in seen[-1]


def test_a_picked_document_the_caller_cannot_read_is_refused_as_missing():
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    r = client.post(f"/api/conversations/{convo}/ask",
                    json={"question": "what is the dry film thickness", "document_ids": ["doc_missing"]})
    assert r.status_code == 404


def test_picking_a_document_makes_an_unmarked_question_a_document_one(monkeypatch):
    _local_model(monkeypatch)
    client = TestClient(app)
    doc = upload(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "what is corrosion allowance", document_ids=[doc])
    # searched in the picked document, never answered from general knowledge
    assert body["answer_type"] != "general"

