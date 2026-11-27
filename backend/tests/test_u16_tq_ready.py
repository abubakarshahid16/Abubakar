"""A technical query opens READY (owner, 26 Nov 2026 21:29 and 21:36): the system proposes the question, prepares the evidence and the LOCAL
model writes a draft with no click in the middle; an edited wording refreshes evidence and draft; confirming is an approval flag, never a
gate; approving confirms the wording the draft answers. Invented documents and wording; no real model, no network."""

from __future__ import annotations

import json

import pytest

from app import db
from app import technical_queries as tq
from app import technical_query_auto as auto
from app import technical_query_jobs as J
from app.access import AccessScope
from app.api import technical_queries as api
from tests.test_technical_queries import envelope, hold_contract
from tests.test_tq_g_feature_off import (  # noqa: F401 - storage is the autouse database fixture
    REVIEWER,
    on,
    storage,
)

QUOTE = "Invented clause 7.1: the flange rating shall be class 300."


@pytest.fixture
def query(monkeypatch):
    """An imported query whose evidence job proposes a question and finds one passage in a held contract (search stood in for)."""
    on(monkeypatch)
    monkeypatch.setattr(J, "AUTO_START", False)
    hold_contract("d1")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES ('d1',3,?,60,0,1)",
            (QUOTE,),
        )
    item, _ = tq.import_message(envelope("ready-1"), "u1", False, False)

    def prepared(
        query_id, allowed, user_id, is_admin, unrestricted, actor, *, progress=None
    ):
        """What prepare_evidence leaves: the proposal, the wording searched and the passage it found for that wording."""
        current = tq.get(query_id, user_id, is_admin, unrestricted)
        question = (
            current.get("confirmed_question")
            or current.get("edited_question")
            or "1. What flange rating applies?"
        )
        with db.connect() as conn:
            from app.technical_query_items import (
                SEARCH_VERSION,  # stamped as the real preparation stamps it
            )

            conn.execute("UPDATE technical_queries SET proposed_question=?,evidence_question=?,evidence_search_version=?,status='drafting' WHERE id=?",
                         ("1. What flange rating applies?", question, str(SEARCH_VERSION), query_id))  # fmt: skip
            conn.execute(
                "INSERT INTO query_evidence(id,query_id,document_id,page_start,page_end,exact_quote,quote_hash,evidence_state,"
                "supersession_state,created_at,found_for,rank_score) VALUES (?,?,'d1',3,3,?,?,'proposed','unknown','x',?,1.0)",
                (
                    f"e-{auto.key(question)}",
                    query_id,
                    QUOTE,
                    auto.key(question),
                    auto.key(question),
                ),
            )
        return tq.get(query_id, user_id, is_admin, unrestricted)

    monkeypatch.setattr(tq, "prepare_evidence", prepared)
    asked = []

    def answer(question, **kwargs):
        asked.append(
            (question, kwargs.get("model"), kwargs.get("allowed_document_ids"))
        )
        return {"answer_type": "generated", "answer": "Class 300 [S1].", "cited": [1], "model": "synthetic-local",
                "passages": [{"document_id": "d1", "page_start": 3, "page_end": 3, "text": QUOTE}]}  # fmt: skip

    monkeypatch.setattr("app.answer.answer", answer)
    return item, AccessScope("u1", frozenset({"d1"}), capabilities=REVIEWER), asked


def _run(query_id):
    with db.connect() as conn:
        job = J.latest(conn, query_id)
    assert job["state"] == "queued"
    J.run_job(job["id"], wait_for_review=False)


def test_one_job_proposes_finds_and_drafts_with_no_click_and_the_local_model_only(
    query,
):
    item, scope, asked = query
    J.enqueue(
        item["id"], scope.readable_with_attachments, "u1", False, False
    )  # as the import does
    _run(item["id"])
    ready = tq.get(item["id"], "u1", False, False)
    assert ready["status"] == "awaiting_review"
    assert asked == [
        ("1. What flange rating applies?", "local", frozenset({"d1"}))
    ]  # never Claude
    draft = ready["drafts"][-1]
    assert (
        draft["system"]
        and draft["prompt_version"] == auto.SYSTEM_DRAFT
        and draft["question"] == "1. What flange rating applies?"
    )
    assert ready["ready"] == {
        "question": "1. What flange rating applies?", "question_source": "proposed", "evidence": "ready", "evidence_fresh": True, "evidence_outdated": False,
        "draft": "ready", "draft_fresh": True, "draft_note": None,
        "marks": ["The AI suggested this question. Nobody has confirmed it yet.", auto.FOUND_NOT_KEPT,
                  "The revision of contract is not confirmed yet. Confirm it under Documents, Details."],
        "cited": [],  # what the contractor's form cites, held or not (none here)
        "items": [],  # the request's numbered items (a single question here)
        # COMPANY's usual cost / schedule sentence, OFFERED beside the draft, never put in (technical_query_position); no money word here
        "position": {"line": "On the information given, COMPANY finds no basis for a change to cost or schedule from this item.", "hint": None, "reply_speaks": False},
        "question_terms": 3,
        "cross_refs": [],  # other queries the request names (none here)
    }  # fmt: skip
    assert (
        json.loads(draft["unresolved_json"]) == ready["ready"]["marks"]
    )  # the same marks travel with the draft


def test_an_edited_wording_refreshes_evidence_and_draft_without_confirming(query):
    item, scope, asked = query
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    edited = api.edit_query_question(
        item["id"],
        api.QuestionIn(question="What flange class applies to line 7?"),
        scope,
    )
    assert (
        edited["edited_question"] == "What flange class applies to line 7?"
        and edited["confirmed_question"] is None
    )
    assert (
        edited["status"] == "drafting"
    )  # the model-written draft answers the old wording
    assert (
        edited["ready"]["evidence"] == "refreshing"
        and edited["ready"]["draft"] == "refreshing"
    )
    assert not edited["ready"]["evidence_fresh"] and not edited["ready"]["draft_fresh"]
    _run(item["id"])
    again = tq.get(item["id"], "u1", False, False)
    assert asked[-1][0] == "What flange class applies to line 7?"
    assert [d["question"] for d in again["drafts"]] == [
        "1. What flange rating applies?",
        "What flange class applies to line 7?",
    ]
    assert (
        again["ready"]["question_source"] == "edited"
        and again["ready"]["evidence_fresh"]
        and again["ready"]["draft_fresh"]
    )
    assert (
        "An engineer changed this question. Nobody has confirmed it yet."
        in again["ready"]["marks"]
    )
    # the old wording's passage folds away: the new draft cites the passage found for the new wording
    assert {e["id"]: e["for_current_question"] for e in again["evidence"]} == {
        f"e-{auto.key('1. What flange rating applies?')}": False, f"e-{auto.key('What flange class applies to line 7?')}": True}  # fmt: skip


def test_confirming_the_same_wording_queues_nothing_and_another_wording_refreshes(
    query,
):
    item, scope, _asked = query
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    same = api.confirm_query_question(
        item["id"], api.QuestionIn(question="1. What flange rating applies?"), scope
    )
    assert (
        same["status"] == "awaiting_review" and same["evidence_job"]["state"] == "done"
    )  # a pure approval flag
    other = api.confirm_query_question(
        item["id"], api.QuestionIn(question="Which flange class?"), scope
    )
    assert other["status"] == "drafting" and other["evidence_job"]["state"] == "queued"


def test_approving_confirms_the_wording_the_draft_answers_and_a_stale_draft_is_never_approved(
    query,
):
    item, scope, _asked = query
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    ready = tq.get(item["id"], "u1", False, False)
    # approval still needs every found passage kept (unchanged), and a kept, current citation
    tq.update_evidence(
        item["id"],
        ready["evidence"][0]["id"],
        "verified",
        "current",
        None,
        "u1",
        "u1",
        False,
        False,
        reviewer=True,
    )
    with (
        db.connect() as conn
    ):  # an engineer types a new wording straight into the table: the draft now answers an older one
        conn.execute(
            "UPDATE technical_queries SET edited_question='Another wording?' WHERE id=?",
            (item["id"],),
        )
    with pytest.raises(ValueError, match="older wording"):
        tq.decide(
            item["id"],
            "approve",
            "u1",
            None,
            ready["drafts"][-1]["id"],
            "u1",
            False,
            False,
            reviewer=True,
        )
    with db.connect() as conn:
        conn.execute(
            "UPDATE technical_queries SET edited_question=NULL WHERE id=?",
            (item["id"],),
        )
    approved = tq.decide(
        item["id"],
        "approve",
        "u1",
        None,
        ready["drafts"][-1]["id"],
        "u1",
        False,
        False,
        reviewer=True,
    )
    assert approved["status"] == "approved"
    assert (
        approved["confirmed_question"] == "1. What flange rating applies?"
        and approved["confirmed_question_by"] == "u1"
    )
    assert any(
        e["event"] == "question_confirmed" and "with the approval" in e["detail"]
        for e in approved["events"]
    )


def test_no_passage_leaves_a_plain_reason_and_an_engineers_own_draft_is_never_replaced(
    query, monkeypatch
):
    item, scope, asked = query
    monkeypatch.setattr(
        tq, "prepare_evidence", lambda *a, **k: None
    )  # nothing found, nothing proposed
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    left = tq.get(item["id"], "u1", False, False)
    assert (
        left["evidence_job"]["state"] == "done" and left["drafts"] == [] and asked == []
    )
    assert (
        left["ready"]["draft"] == "not_written"
        and left["ready"]["draft_note"] == auto.NO_QUESTION
    )
    tq.add_draft(
        item["id"], "Typed by an engineer.", [], [], "u1", "u1", False, False
    )  # model None: an engineer's own draft
    with db.connect() as conn:
        conn.execute(
            "UPDATE technical_queries SET status='drafting',proposed_question='Q?' WHERE id=?",
            (item["id"],),
        )
    assert (
        auto.write_draft(item["id"], frozenset({"d1"}), "u1", False, False)
        == auto.TYPED_KEPT
    )
    assert [d["answer"] for d in tq.get(item["id"], "u1", False, False)["drafts"]] == [
        "Typed by an engineer."
    ]


def test_the_queries_not_ready_are_queued_at_start_with_their_owners_scope(
    query, monkeypatch
):
    item, _scope, _asked = query
    ownerless, _ = tq.import_message(
        {**envelope("ready-2"), "provider_thread_id": "thread-2"}, "u1", False, False
    )
    with db.connect() as conn:  # its owner's account was removed (ON DELETE SET NULL)
        conn.execute(
            "UPDATE technical_queries SET owner_user_id=NULL WHERE id=?",
            (ownerless["id"],),
        )
    seen = []
    monkeypatch.setattr(
        J,
        "enqueue",
        lambda qid, allowed, user, *a, **k: seen.append(
            (qid, user, k.get("start_thread"))
        ),
    )
    assert auto.queue_backlog() == 1
    assert (
        seen == [(item["id"], "u1", False)]
    )  # one at a time on the app's one thread; a query with no owner waits for the button
    with db.connect() as conn:
        assert set(auto.backlog(conn)) == {item["id"], ownerless["id"]}


def test_a_query_with_no_wording_has_no_evidence_for_it_even_with_older_finds(query):
    """Measured on a copy (26 Nov 2026): a query with no question showed 'evidence ready, 20 found for this wording' because the old
    rows' empty fingerprint matched the empty wording."""
    item, _scope, _asked = query
    with db.connect() as conn:
        conn.execute(
            "UPDATE technical_queries SET proposed_question=NULL WHERE id=?",
            (item["id"],),
        )
        conn.execute(
            "INSERT INTO query_evidence(id,query_id,document_id,page_start,page_end,exact_quote,quote_hash,evidence_state,"
            "supersession_state,created_at) VALUES ('old',?,'d1',3,3,?,'h','proposed','unknown','x')",
            (item["id"], QUOTE),
        )
    got = tq.get(item["id"], "u1", False, False)
    assert (
        got["ready"]["question_source"] == "none" and got["ready"]["evidence"] == "none"
    )
    assert [e["for_current_question"] for e in got["evidence"]] == [False]


def test_approval_needs_no_decision_on_an_earlier_wordings_finds_and_a_source_confirmed_with_sign_in_off_counts(
    query,
):
    """Builder C's walk on the measured copy (26 Nov 2026): 27 passages found for an earlier wording blocked approval, and a source
    confirmed on an install with sign-in off (no actor id: confirmed_at set, confirmed_by empty) stayed "unknown" for ever."""
    item, scope, _asked = query
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    with db.connect() as conn:
        for n, found_for in enumerate(
            ("an-older-wording", None)
        ):  # one known to be another wording's, one with no record
            conn.execute(
                "INSERT INTO query_evidence(id,query_id,document_id,page_start,page_end,exact_quote,quote_hash,evidence_state,"
                "supersession_state,created_at,found_for) VALUES (?,?,'d1',3,3,?,?,'proposed','unknown','x',?)",
                (f"old{n}", item["id"], QUOTE, f"h{n}", found_for),
            )
        conn.execute(
            "UPDATE document_classification SET confirmed_by=NULL, confirmed_at='2026-11-26T20:00:00Z' WHERE document_id='d1'"
        )
    ready = tq.get(item["id"], "u1", False, False)
    assert {e["id"]: e["supersession_state"] for e in ready["evidence"]}[
        f"e-{auto.key('1. What flange rating applies?')}"
    ] == "current"
    cited = next(e["id"] for e in ready["evidence"] if e["for_current_question"])
    tq.update_evidence(
        item["id"],
        cited,
        "verified",
        "current",
        None,
        "u1",
        "u1",
        False,
        False,
        reviewer=True,
    )
    # the query was prepared again, so neither the other wording's find nor the row with no record needs a decision (lead-4)
    approved = tq.decide(
        item["id"],
        "approve",
        "u1",
        None,
        ready["drafts"][-1]["id"],
        "u1",
        False,
        False,
        reviewer=True,
    )
    assert (
        approved["status"] == "approved"
    )  # the other wording's untouched find did not block it


def test_a_row_with_no_wording_record_needs_no_decision_once_the_query_was_prepared_again(
    query,
):
    """Builder C's walk (26 Nov 2026): 16-27 rows per query from preparations before wordings were recorded blocked approval on all 33.
    Once the query is prepared again (evidence_question set), such a row was not found by the current search."""
    item, scope, _asked = query
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO query_evidence(id,query_id,document_id,page_start,page_end,exact_quote,quote_hash,evidence_state,"
            "supersession_state,created_at) VALUES ('older',?,'d1',3,3,?,'h-old','proposed','unknown','x')",
            (item["id"], QUOTE),
        )
        conn.execute(
            "UPDATE document_classification SET confirmed_by='u1' WHERE document_id='d1'"
        )
    ready = tq.get(item["id"], "u1", False, False)
    found = next(e["id"] for e in ready["evidence"] if e["for_current_question"])
    tq.update_evidence(
        item["id"],
        found,
        "verified",
        "current",
        None,
        "u1",
        "u1",
        False,
        False,
        reviewer=True,
    )
    with (
        db.connect() as conn
    ):  # the same query as it was before it was prepared again: the no-record row still needs a decision
        conn.execute(
            "UPDATE technical_queries SET evidence_question=NULL WHERE id=?",
            (item["id"],),
        )
    with pytest.raises(ValueError, match="before approval"):
        tq.decide(
            item["id"],
            "approve",
            "u1",
            None,
            ready["drafts"][-1]["id"],
            "u1",
            False,
            False,
            reviewer=True,
        )
    with db.connect() as conn:
        conn.execute(
            "UPDATE technical_queries SET evidence_question=? WHERE id=?",
            (ready["evidence_question"], item["id"]),
        )
    approved = tq.decide(
        item["id"],
        "approve",
        "u1",
        None,
        ready["drafts"][-1]["id"],
        "u1",
        False,
        False,
        reviewer=True,
    )
    assert approved["status"] == "approved"
