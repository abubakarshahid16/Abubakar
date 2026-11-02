# ruff: noqa: F811
"""The AI clause review on the Claude lane, and the local path's honest limit line.

The Batch API is a fake; no socket, no real model, no real document. Every text here is invented.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

import pytest

from app import (
    absence,
    access,
    claude_batch_run,
    claude_spend,
    clause_review,
    clause_review_claude,
    clause_review_status,
    db,
    document_refs,
    review_audit,
    submittal_review,
)
from app import (
    main as main_mod,
)
from app import reasoning_provider as rp
from app.config import settings
from tests.test_1477_clause_review import (  # noqa: F401 - fixtures and helpers
    GOOD_CHAIR,
    PAGE1,
    REQ_ACTIONS,
    REQ_CHAIR,
    REQ_GUIDE,
    Fake,
    _resolver,
    _rows,
    _world,
    on,
)
from tests.test_b3_page_ledger import NOW, temp_storage  # noqa: F401 - autouse
from tests.test_chat_pr1_model_lane import KEY

NO_EVIDENCE = {"answer": "no_evidence", "page": None, "quote": None}
QUOTED = {"answer": "quote", "page": 1, "quote": GOOD_CHAIR}
#: On a page of the document, about nothing any requirement here asks.
PLANTED = "Quartermaster zebra manifests accumulate beneath the eastern loading gantry."


class Batches:
    """Holds what it was sent. A batch stays in progress until `ended`; `kinds` scripts a request's result."""

    def __init__(
        self, *, ended=True, answer=None, kinds=None, stop="end_turn", output=100
    ):
        self.created, self.ended, self.retrieves = [], ended, 0
        self.answer = answer or (lambda text: NO_EVIDENCE)
        self.kinds, self.stop, self.output = kinds or {}, stop, output

    def batch_create(self, url, *, headers, requests):
        self.created.append(requests)
        return {
            "id": f"msgbatch_{len(self.created)}",
            "processing_status": "in_progress",
        }

    def batch_retrieve(self, url, batch_id, *, headers):
        self.retrieves += 1
        state = "ended" if self.ended else "in_progress"
        return {
            "id": batch_id,
            "processing_status": state,
            "results_url": "https://x/r",
        }

    def batch_results(self, url, *, headers):
        rows = []
        for request in self.created[-1]:
            scripted = self.kinds.get("*") or []
            kind = scripted.pop(0) if scripted else "succeeded"
            result = {"type": kind}
            if kind == "succeeded":
                reply = self.answer(json.dumps(request["params"]["messages"]))
                text = reply if isinstance(reply, str) else json.dumps(reply)
                result["message"] = {
                    "model": "claude-sonnet-5-answered",
                    "stop_reason": self.stop,
                    "usage": {"input_tokens": 2000, "output_tokens": self.output},
                    "content": [{"type": "text", "text": text}],
                }
            rows.append({"custom_id": request["custom_id"], "result": result})
        return rows

    def sent(self):
        return [r for batch in self.created for r in batch]


@pytest.fixture
def lane(tmp_path, monkeypatch, on):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    monkeypatch.setattr(settings, "ai_clause_review_engine", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", KEY)
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    clause_review_claude._PACKETS.clear()


@pytest.fixture
def fake(lane, monkeypatch):
    batches = Batches()
    monkeypatch.setattr(clause_review_claude, "_client", lambda: batches)
    return batches


def _reqs(n):
    return tuple(f"Item {i}: The HAZOP chair shall be independent." for i in range(n))


def _start(run, scope):
    clause_review.for_review(run, scope)
    return clause_review.status_of(run)


def _second_run(sub, scope):
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET status = 'completed'")
    run = submittal_review.create_review_run(
        submittal_document_id=sub, allowed_document_ids=scope
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,selection_reason,"
            "selection_method,included,created_at) VALUES (?,?,?,'cited','referenced',1,?)",
            (str(uuid.uuid4()), run, "doc_std", NOW),
        )
    return run


def _batch_rows(table, run):
    return (
        db.connect()
        .execute(
            f"SELECT COUNT(*) FROM {table} WHERE job = ?",
            (clause_review_claude._job(run),),
        )
        .fetchone()[0]
    )


# ---------------------------------------------------------------- the setting


def test_the_engine_is_local_by_default_and_nothing_reaches_the_batch(on, monkeypatch):
    assert settings.ai_clause_review_engine == "ollama"
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    assert clause_review_claude.for_review("no-run", frozenset()) == (False, None)


def test_the_provider_switch_still_wins_over_the_engine_setting(fake, monkeypatch):
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    made = []
    monkeypatch.setattr(
        rp, "OllamaProvider", lambda **k: made.append(1) or Fake({"HAZOP": NO_EVIDENCE})
    )
    _sub, run, scope = _world()
    status = _start(run, scope)
    assert fake.created == [] and made
    assert "Claude was asked for and not used (PROVIDER_OFF)" in status["plain"]


def test_per_task_with_a_local_engine_stays_local(fake, monkeypatch):
    monkeypatch.setattr(settings, "ai_clause_review_engine", "ollama")
    monkeypatch.setattr(rp, "OllamaProvider", lambda **k: Fake({"HAZOP": NO_EVIDENCE}))
    _sub, run, scope = _world()
    _start(run, scope)
    assert fake.created == []


# ------------------------------------------------------------- every requirement


def test_every_applicable_requirement_is_reviewed_past_the_local_limit(fake):
    assert settings.clause_review_max_requirements == 60
    _sub, run, scope = _world(_reqs(65))
    status = _start(run, scope)
    assert len(fake.sent()) == 65 and len(_rows(run)) == 65
    assert status["results"]["reviewed"] == 65 and status["results"]["adds_up"]
    assert status["results"]["applicable"] == 65 and status["not_reviewed"] == []
    assert not status["pending"] and "65 of 65 requirement(s) read" in status["plain"]
    assert "not AI-reviewed" not in status["plain"]
    assert "over the local engine" not in status["plain"]


def test_one_ask_carries_one_rule_and_its_passages_never_the_document(fake):
    filler = " ".join(f"Sentence {i} about the HAZOP chair role." for i in range(600))
    sub, run, scope = _world((REQ_CHAIR,))
    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET text = ? WHERE document_id = ? AND page_no = 1",
            (filler, sub),
        )
        conn.execute(
            "UPDATE chunks SET text = ? WHERE document_id = ? AND ordinal = 1",
            (filler, sub),
        )
        conn.execute(
            "UPDATE pages SET text = ? WHERE document_id = ? AND page_no = 2",
            (PLANTED, sub),
        )
        conn.execute(
            "UPDATE chunks SET text = ? WHERE document_id = ? AND ordinal = 2",
            (PLANTED, sub),
        )
    _start(run, scope)
    [ask] = fake.sent()
    shown = json.dumps(ask["params"]["messages"])
    assert REQ_CHAIR in shown and PLANTED not in shown
    assert filler not in shown and "Sentence 599" not in shown
    assert (
        len(ask["params"]["messages"][0]["content"])
        < 2 * 4 * clause_review.PASSAGE_CHARS
    )


def test_the_examples_go_in_the_cached_system_block_not_in_each_question(fake):
    _sub, run, scope = _world()
    _start(run, scope)
    [ask] = fake.sent()
    [block] = ask["params"]["system"]
    assert block["cache_control"] == {"type": "ephemeral"}
    assert "DECISION EXAMPLES" in block["text"]
    assert "DECISION EXAMPLES" not in json.dumps(ask["params"]["messages"])


# ------------------------------------------------------------ what code decides


def _answer_by_requirement(text):
    if "HAZOP chair" in text:
        return QUOTED
    if "tracked to closure" in text:
        return {
            "answer": "quote",
            "page": 2,
            "quote": "words the model made up and no page holds",
        }
    return "not json at all"


def test_each_outcome_is_counted_and_only_a_verified_quote_is_evidence(fake):
    fake.answer = _answer_by_requirement
    _sub, run, scope = _world((REQ_CHAIR, REQ_ACTIONS, REQ_GUIDE))
    status = _start(run, scope)
    assert status["results"] == {
        "applicable": 3, "reviewed": 2, "verified_quote": 1, "no_passage_found": 0,
        "unverifiable": 1, "unreadable": 1, "failed": 0, "not_reviewed": 0, "adds_up": True,
    }  # fmt: skip
    rows = {r["standard_clause"]: r for r in _rows(run)}
    assert rows["5.1"]["contractor_evidence_text"] == GOOD_CHAIR
    assert rows["5.2"]["contractor_evidence_text"] is None
    assert rows["5.2"]["contractor_page"] is None
    assert rows["5.3"]["contractor_evidence_text"] is None
    assert "1 with an unreadable answer" in status["plain"]


def test_no_row_decides_a_verdict_or_counts_in_a_headline(fake):
    fake.answer = lambda text: QUOTED
    _sub, run, scope = _world()
    _start(run, scope)
    [row] = _rows(run)
    assert row["compliance_status"] == clause_review.NEEDS_ENGINEER_REVIEW
    assert row["confirmed_by"] is None and row["confidence"] == "low"
    assert row["finding"].startswith(clause_review.TEXT_VERIFIED)
    assert clause_review.without_rows([row]) == []
    assert row["ai_rationale"].startswith(clause_review.LABEL)


def test_an_answer_cut_off_is_unreadable_however_good_its_text(fake):
    fake.answer, fake.stop = (lambda text: QUOTED), "max_tokens"
    _sub, run, scope = _world()
    status = _start(run, scope)
    assert status["unreadable"] == 1 and status["verified"] == 0


def test_a_fenced_answer_is_read(fake):
    fake.answer = lambda text: "```json\n" + json.dumps(QUOTED) + "\n```"
    _sub, run, scope = _world()
    assert _start(run, scope)["verified"] == 1


# ------------------------------------------------- waiting does not block the app


def test_a_batch_out_returns_at_once_and_says_pending_on_the_crs_and_the_audit(
    fake, monkeypatch
):
    fake.ended = False
    slept = []
    monkeypatch.setattr(claude_batch_run.time, "sleep", slept.append)
    monkeypatch.setattr(settings, "review_audit_report_enabled", True)
    _sub, run, scope = _world((REQ_CHAIR, REQ_ACTIONS))
    status = _start(run, scope)
    assert slept == [] and fake.retrieves == 1 and len(fake.created) == 1
    assert status["pending"] is True and _rows(run) == []
    assert status["results"]["not_reviewed"] == 2 and status["results"]["reviewed"] == 0
    assert clause_review_claude.WHY_WAITING in status["plain"]
    assert "2 of 2 applicable requirement(s) not AI-reviewed" in status["plain"]
    assert status["calls"] == 2
    assert status["usd"]["held"] > 0 and status["usd"]["charged"] == 0
    _r, meta, _n, _s = main_mod._crs_content(
        run, access.unrestricted_scope(), "internal"
    )
    assert any(status["plain"] in n["detail"] for n in meta["review_notes"])
    assert "REVIEW INCOMPLETE" in meta["incomplete_notice"]
    audit = review_audit.build(run, access.unrestricted_scope(), None)
    [step] = [s for s in audit["ai_use"]["steps"] if s["name"] == "clause_review"]
    assert step["state"] == "pending" and step["results"]["not_reviewed"] == 2
    assert status["plain"] in review_audit.render_markdown(audit)


def test_a_restart_polls_the_same_batch_and_pays_once(fake):
    fake.ended = False
    _sub, run, scope = _world((REQ_CHAIR, REQ_ACTIONS))
    _start(run, scope)
    clause_review_claude._PACKETS.clear()  # the process died; only the database remains
    fake.ended = True
    status = clause_review_claude.tick(run)
    assert len(fake.created) == 1 and len(_rows(run)) == 2
    assert status["pending"] is False and status["results"]["reviewed"] == 2
    assert (
        status["calls"] == 2
        and status["usd"]["held"] == 0
        and status["usd"]["charged"] > 0
    )


def test_a_retried_review_job_does_not_send_a_second_batch(fake):
    fake.ended = False
    _sub, run, scope = _world()
    _start(run, scope)
    _start(run, scope)
    assert len(fake.created) == 1


def test_only_a_due_poll_runs_and_a_failing_poll_never_raises(fake, monkeypatch):
    fake.ended = False
    _sub, run, scope = _world()
    _start(run, scope)
    before = fake.retrieves
    assert clause_review_claude.poll_due() == 0 and fake.retrieves == before
    later = (
        clause_review_claude.time.time() + settings.clause_review_batch_poll_seconds + 1
    )
    assert clause_review_claude.poll_due(now=lambda: later) == 1
    assert fake.retrieves == before + 1

    def down(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(fake, "batch_retrieve", down)
    later += settings.clause_review_batch_poll_seconds + 1
    assert clause_review_claude.poll_due(now=lambda: later) == 1
    assert clause_review.status_of(run)["pending"] is True


def test_with_no_table_the_idle_poll_does_nothing():
    assert clause_review_claude.poll_due() == 0


def test_the_idle_worker_loop_polls(monkeypatch):
    from app import ingest

    worker = ingest.IngestionWorker.__new__(ingest.IngestionWorker)
    worker._stop = ingest.threading.Event()
    worker.poll_seconds = 0
    worker.last_error = None
    turns = []

    def next_document():  # a loop that forgot the poll still ends, and the assert below fails
        turns.append(1)
        if len(turns) > 1:
            worker._stop.set()

    monkeypatch.setattr(worker, "_next_document", next_document, raising=False)
    monkeypatch.setattr(worker, "_drain_review_jobs", lambda: False, raising=False)
    monkeypatch.setattr(
        worker, "_drain_standard_extraction", lambda: False, raising=False
    )
    polled = []

    monkeypatch.setattr(clause_review_claude, "poll_due", lambda: polled.append(1))
    worker._run()
    assert polled


def test_the_lane_shut_while_waiting_makes_no_poll_and_stays_pending(fake, monkeypatch):
    fake.ended = False
    _sub, run, scope = _world()
    _start(run, scope)
    before = fake.retrieves
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    status = clause_review_claude.tick(run)
    assert fake.retrieves == before and status["pending"] is True


def _later(hours):
    at = clause_review_claude.time.time() + hours * 3600
    return lambda: at


def test_a_batch_sent_and_not_ended_past_the_limit_stays_pending_and_is_still_read(
    fake,
):
    fake.ended = False
    _sub, run, scope = _world((REQ_CHAIR, REQ_ACTIONS))
    _start(run, scope)
    status = clause_review_claude.tick(run, now=_later(27))
    assert status["pending"] is True and _rows(run) == []
    assert "it was sent and its result was not read within 26 h" in status["plain"]
    assert "never sent" not in status["plain"]
    assert status["usd"]["held"] > 0 and status["usd"]["charged"] == 0
    fake.ended = True  # the paid result turns up
    status = clause_review_claude.tick(run, now=_later(30))
    assert status["pending"] is False and len(_rows(run)) == 2
    assert status["results"]["reviewed"] == 2
    assert status["usd"]["held"] == 0 and status["usd"]["estimated"] == 0
    assert len(fake.created) == 1


def test_polls_failing_past_the_limit_lose_no_paid_result(fake):
    fake.ended = False
    _sub, run, scope = _world()
    _start(run, scope)
    working = fake.batch_retrieve

    def down(*a, **k):
        raise OSError("network down")

    fake.batch_retrieve = down
    status = clause_review_claude.tick(run, now=_later(40))
    assert status["pending"] is True and "it was sent" in status["plain"]
    assert "never sent" not in status["plain"]
    fake.batch_retrieve, fake.ended = working, True
    status = clause_review_claude.tick(run, now=_later(41))
    assert status["pending"] is False and len(_rows(run)) == 1
    assert status["usd"]["estimated"] == 0 and status["usd"]["charged"] > 0


def test_the_lane_shut_past_the_limit_says_sent_not_read_and_reads_when_it_opens(
    fake, monkeypatch
):
    fake.ended = False
    _sub, run, scope = _world()
    _start(run, scope)
    before = fake.retrieves
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    status = clause_review_claude.tick(run, now=_later(27))
    assert fake.retrieves == before and status["pending"] is True
    assert "did not return" not in status["plain"]
    assert "it was sent and its result was not read" in status["plain"]
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    fake.ended = True
    status = clause_review_claude.tick(run, now=_later(28))
    assert status["pending"] is False and len(_rows(run)) == 1


def test_an_ask_never_sent_is_counted_never_sent_and_is_not_sent_past_the_limit(
    fake, monkeypatch
):
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", _worst_one() * 1.5)
    fake.ended = False
    _sub, run, scope = _world(_reqs(3))
    _start(run, scope)  # one fits at worst case, two wait for the room
    assert [len(b) for b in fake.created] == [1]
    pending = clause_review.status_of(run)
    assert "2 because it has not been sent to Claude yet" in pending["plain"]
    fake.ended = True
    status = clause_review_claude.tick(run, now=_later(27))
    assert [len(b) for b in fake.created] == [1]  # nothing new goes out
    assert status["pending"] is False and status["results"]["reviewed"] == 1
    assert (
        "2 because it was never sent to Claude within the 26 h limit" in status["plain"]
    )
    assert "did not return" not in status["plain"]


def test_past_the_read_window_an_unread_ask_is_charged_at_worst_case_and_says_so(
    fake, monkeypatch
):
    fake.ended = False
    _sub, run, scope = _world((REQ_CHAIR, REQ_ACTIONS))
    held = _start(run, scope)["usd"]["held"]
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    status = clause_review_claude.tick(run, now=_later(30 * 24))
    assert status["pending"] is False and status["results"]["not_reviewed"] == 2
    assert status["usd"]["held"] == 0
    assert status["usd"]["charged"] == pytest.approx(held)
    assert status["usd"]["estimated"] == pytest.approx(held)
    assert "estimated at worst case because the bill is unknown" in status["plain"]
    assert "held at worst case" not in status["plain"]
    assert "could not be read within 29 days" in status["plain"]
    assert claude_spend.spent("clause_review") == pytest.approx(held)


def test_a_closed_run_holds_nothing_and_a_real_bill_is_not_called_estimated(fake):
    _sub, run, scope = _world()
    status = _start(run, scope)
    assert status["usd"]["held"] == 0 and status["usd"]["estimated"] == 0
    assert "held at worst case" not in status["plain"]
    assert "estimated" not in status["plain"]


def test_a_cancelled_run_charges_what_it_held_once(fake):
    fake.ended = False
    _sub, run, scope = _world()
    held = _start(run, scope)["usd"]["held"]
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET status = 'cancelled' WHERE id = ?", (run,))
    assert clause_review_claude.tick(run) is None
    assert clause_review_claude.tick(run) is not False
    lines = [e for e in claude_spend.entries() if e.get("run") == run]
    assert [bool(e.get("reserved")) for e in lines] == [False]
    assert sum(e["cost_usd"] for e in lines) == pytest.approx(held)


def test_a_deleted_submittal_leaves_no_open_hold(fake):
    fake.ended = False
    sub, run, scope = _world()
    _start(run, scope)
    conn = db.connect()
    with conn:
        document_refs.forget_quotes(conn, sub)
    assert not [e for e in claude_spend.entries() if e.get("reserved")]


def test_late_answers_never_land_on_a_run_with_an_engineers_final_code(
    fake, monkeypatch
):
    numbered = []
    monkeypatch.setattr(main_mod, "number_crs_rows", lambda r, s: numbered.append(r))
    fake.answer, fake.ended = (lambda text: QUOTED), False
    sub, run, scope = _world()
    _start(run, scope)
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_runs SET engineer_final_code = '1', status = 'completed' WHERE id = ?",
            (run,),
        )
    fake.ended = True
    status = clause_review_claude.tick(run)
    assert _rows(run) == [] and numbered == []
    assert status["results"]["reviewed"] == 0 and status["results"]["not_reviewed"] == 1
    assert status["results"]["adds_up"]
    assert "engineer's final code" in status["plain"]
    assert status["usd"]["charged"] > 0  # the paid answer is settled, not lost
    fresh = _second_run(sub, scope)  # and a new review reads it at no cost
    again = _start(fresh, scope)
    assert (
        len(fake.created) == 1 and again["cache_hits"] == 1 and len(_rows(fresh)) == 1
    )


def test_the_close_of_a_decided_run_numbers_nothing_and_still_writes_the_audit(
    fake, monkeypatch
):
    from app import review_jobs

    sub, first, scope = _world()
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_runs SET status = 'completed' WHERE id = ?", (first,)
        )
    run, _job = review_jobs.enqueue(sub, allowed_document_ids=scope, requested_by=None)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,selection_reason,"
            "selection_method,included,created_at) VALUES (?,?,?,'cited','referenced',1,?)",
            (str(uuid.uuid4()), run, "doc_std", NOW),
        )
    numbered, audited = [], []
    monkeypatch.setattr(main_mod, "number_crs_rows", lambda r, s: numbered.append(r))
    monkeypatch.setattr(review_audit, "write", lambda r, s, t: audited.append(r))
    fake.ended = False
    _start(run, scope)
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_runs SET engineer_final_code = '1' WHERE id = ?", (run,)
        )
    fake.ended = True
    clause_review_claude.tick(run)
    assert numbered == [] and audited == [run]


def test_expired_or_cancelled_twice_is_not_reviewed_and_never_sent_again(fake):
    fake.kinds = {"*": ["expired", "canceled"]}
    _sub, run, scope = _world()
    status = _start(run, scope)
    assert len(fake.created) == 2  # the first send and one re-queue
    assert status["results"]["not_reviewed"] == 1 and status["results"]["failed"] == 0
    assert "canceled twice" in status["plain"] and _rows(run) == []
    # the close is final: `run` would re-queue a given-up request
    assert (
        clause_review_claude.tick(run)["plain"] == status["plain"]
        and len(fake.created) == 2
    )


def test_a_given_up_request_is_not_resent_by_the_next_poll_of_the_others(
    fake, monkeypatch
):
    """`claude_batch_run.run` re-queues what was given up each call; a polling caller keeps it out."""
    fake.ended = False
    _sub, run, scope = _world((REQ_CHAIR, REQ_ACTIONS))
    _start(run, scope)
    conn = db.connect()
    job = clause_review_claude._job(run)
    first = conn.execute(
        "SELECT custom_id FROM claude_batch_requests WHERE job = ? LIMIT 1", (job,)
    ).fetchone()["custom_id"]
    with conn:
        conn.execute(
            "UPDATE claude_batch_requests SET state = 'gave_up', failure = 'expired', attempts = 2"
            " WHERE job = ? AND custom_id = ?",
            (job, first),
        )
    fake.ended = True
    status = clause_review_claude.tick(run)
    assert len(fake.created) == 1
    assert status["results"]["reviewed"] == 1 and status["results"]["not_reviewed"] == 1


def test_errored_twice_is_failed(fake):
    fake.kinds = {"*": ["errored", "errored"]}
    _sub, run, scope = _world()
    status = _start(run, scope)
    assert status["results"]["failed"] == 1 and status["results"]["not_reviewed"] == 0
    assert "1 failed (no answer)" in status["plain"]


def test_a_batch_provably_not_taken_closes_partial_and_costs_nothing(fake, monkeypatch):
    from app.reader_transport import TransportRefused

    def refuse(*a, **k):
        raise TransportRefused("not sent")

    monkeypatch.setattr(fake, "batch_create", refuse)
    _sub, run, scope = _world()
    status = _start(run, scope)
    assert status["pending"] is False and status["results"]["not_reviewed"] == 1
    assert "the batch was not accepted" in status["plain"]
    assert status["usd"]["charged"] == 0 and status["usd"]["held"] == 0


def test_a_create_that_may_have_worked_is_said_so_and_stays_charged(fake, monkeypatch):
    def lost(*a, **k):
        raise OSError("read timed out")

    monkeypatch.setattr(fake, "batch_create", lost)
    _sub, run, scope = _world()
    status = _start(run, scope)
    assert status["pending"] is False and status["results"]["not_reviewed"] == 1
    assert clause_review_claude.WHY_UNCONFIRMED in status["plain"]
    assert status["usd"]["held"] == 0 and "never sent" not in status["plain"]
    # charged once, though the close looks at it again
    assert status["usd"]["estimated"] == pytest.approx(
        status["usd"]["worst_case_all"], abs=0.0001
    )


# ------------------------------------------------------------------- the USD cap


def _worst_one():
    packet = clause_review_claude.packet_for(
        "procedure",
        {"clause": "5.1", "requirement_text": _reqs(1)[0]},
        [{"page": 1, "text": PAGE1}],
    )
    return claude_batch_run.worst_usd(settings.claude_reasoning_model, packet)


def test_what_a_cap_leaves_is_sent_in_tranches_and_the_cap_is_never_crossed(
    fake, monkeypatch
):
    """Reservations are at worst case; settled at real cost, the room grows and the next tranche goes."""
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", _worst_one() * 2.5)
    _sub, run, scope = _world(_reqs(5))
    status = clause_review.for_review(run, scope) or clause_review.status_of(run)
    for _ in range(6):
        if not status["pending"]:
            break
        status = clause_review_claude.tick(run)
    assert [len(b) for b in fake.created][:1] == [2] and len(fake.created) >= 2
    assert status["results"]["reviewed"] == 5 and len(_rows(run)) == 5
    assert claude_spend.spent("clause_review") <= settings.claude_budget_usd_per_step


def test_when_the_real_spend_reaches_the_cap_it_stops_partial_with_the_count(
    fake, monkeypatch
):
    cap = _worst_one() * 2.5
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", cap)
    fake.output = 1000  # a real answer close to the worst case: nothing is freed
    _sub, run, scope = _world(_reqs(5))
    clause_review.for_review(run, scope)
    status = clause_review.status_of(run)
    for _ in range(6):
        if not status["pending"]:
            break
        status = clause_review_claude.tick(run)
    assert status["pending"] is False
    assert settings.claude_budget_usd_per_step == cap  # never raised
    assert claude_spend.spent("clause_review") <= cap
    assert 0 < status["results"]["reviewed"] < 5
    assert status["results"]["not_reviewed"] == 5 - status["results"]["reviewed"]
    assert status["results"]["adds_up"]
    assert f"{status['results']['not_reviewed']} of 5 applicable" in status["plain"]
    assert (
        "cap of step clause_review" in status["plain"]
        and "owner's decision" in status["plain"]
    )


def test_with_no_room_at_all_nothing_is_sent_and_every_one_is_counted(
    fake, monkeypatch
):
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", _worst_one() / 2)
    _sub, run, scope = _world(_reqs(3))
    status = _start(run, scope)
    assert fake.created == [] and status["pending"] is False
    assert status["results"]["not_reviewed"] == 3 and status["usd"]["charged"] == 0


def test_the_usd_is_this_runs_and_matches_the_ledger(fake):
    claude_spend.record(
        step="clause_review", model="claude-sonnet-5", usage={"input_tokens": 1000, "output_tokens": 1},
        prompt_sha256="", wall_time_s=0.0, finish_reason="stop",
    )  # fmt: skip
    _sub, run, scope = _world((REQ_CHAIR, REQ_ACTIONS))
    status = _start(run, scope)
    expected = 2 * (2000 * 2.0 + 100 * 10.0) / 1_000_000 * 0.5
    assert status["usd"]["charged"] == pytest.approx(expected)
    assert f"USD {expected:.4f} charged" in status["plain"]
    assert claude_spend.spent("clause_review") > status["usd"]["charged"]


def test_351_asks_whose_worst_case_is_over_the_cap_all_get_done_under_it(
    fake, monkeypatch
):
    """The order's real count, on a model that thinks by default: reserved at worst case the first
    batch cannot hold them all, and no batch ever holds more than the USD 5."""
    monkeypatch.setattr(settings, "claude_reasoning_model", "claude-sonnet-5-5")
    assert settings.claude_budget_usd_per_step == 5.0
    _sub, run, scope = _world(_reqs(351))
    clause_review.for_review(run, scope)
    status = clause_review.status_of(run)
    assert status["usd"]["worst_case_all"] > 5.0
    for _ in range(6):
        if not status["pending"]:
            break
        status = clause_review_claude.tick(run)
    sizes = [len(batch) for batch in fake.created]
    assert sizes[0] < 351 and sum(sizes) == 351
    assert status["results"]["reviewed"] == 351 and len(_rows(run)) == 351
    assert claude_spend.spent("clause_review") <= 5.0


def test_the_close_numbers_the_late_rows_and_writes_the_audit_again(fake, monkeypatch):
    from app import review_jobs

    sub, first, scope = _world()
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_runs SET status = 'completed' WHERE id = ?", (first,)
        )
    run, _job = review_jobs.enqueue(sub, allowed_document_ids=scope, requested_by=None)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,selection_reason,"
            "selection_method,included,created_at) VALUES (?,?,?,'cited','referenced',1,?)",
            (str(uuid.uuid4()), run, "doc_std", NOW),
        )
    numbered, audited = [], []
    monkeypatch.setattr(main_mod, "number_crs_rows", lambda r, s: numbered.append(r))
    monkeypatch.setattr(review_audit, "write", lambda r, s, t: audited.append(r))
    fake.ended = False
    _start(run, scope)
    assert (
        numbered == [] and audited == []
    )  # the review job does its own while it is pending
    fake.ended = True
    clause_review_claude.tick(run)
    assert numbered == [run] and audited == [run]


def test_refused_in_a_barred_run_is_said_and_the_local_engine_stays_out(
    fake, monkeypatch
):
    from app import local_engine_bar

    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    monkeypatch.setattr(
        rp, "OllamaProvider", lambda **k: pytest.fail("the local engine loaded")
    )
    _sub, run, scope = _world()
    with local_engine_bar.bar():
        clause_review.for_review(run, scope)
    status = clause_review.status_of(run)
    assert fake.created == [] and status["ran"] is False
    assert local_engine_bar.NOTE in status["plain"]
    assert "Claude was asked for and not used" in status["plain"]


# ------------------------------------------------------ the approved list and cache


def _list(tmp_path, monkeypatch, rows):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    (tmp_path / "claude_approved_documents.json").write_text(
        json.dumps({"documents": rows}), encoding="utf-8"
    )


def test_a_document_not_on_the_approved_list_sends_nothing(fake, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    _sub, run, scope = _world()
    _list(tmp_path, monkeypatch, [])
    monkeypatch.setattr(rp, "OllamaProvider", lambda **k: Fake({"HAZOP": NO_EVIDENCE}))
    status = _start(run, scope)
    assert fake.created == []
    assert "Claude was asked for and not used" in status["plain"]


def test_a_blocked_document_sends_nothing_whatever_the_list_says(
    fake, monkeypatch, tmp_path
):
    sub, run, scope = _world()
    _list(
        tmp_path, monkeypatch,
        [{"sha256": f"sha-{sub}", "document_id": sub, "status": "blocked"}],
    )  # fmt: skip
    monkeypatch.setattr(rp, "OllamaProvider", lambda **k: Fake({"HAZOP": NO_EVIDENCE}))
    _start(run, scope)
    assert fake.created == []


def test_all_approved_goes_and_declares_the_documents_it_carries(
    fake, monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    sub, run, scope = _world()
    _list(
        tmp_path, monkeypatch,
        [
            {"sha256": sha, "document_id": d, "status": "approved"}
            for d, sha in ((sub, f"sha-{sub}"), ("doc_std", "sha-std"))
        ],
    )  # fmt: skip
    assert _start(run, scope)["results"]["reviewed"] == 1 and len(fake.created) == 1


def test_a_list_withdrawn_before_the_send_stops_it_at_the_gate(fake, monkeypatch):
    """The gate asks again where every call reserves: a stop there closes partial, nothing sent."""

    def refuse(*a, **k):
        raise claude_spend.DocumentNotApproved("NOT_APPROVED", "ids only")

    monkeypatch.setattr(claude_spend, "reserve_all", refuse)
    _sub, run, scope = _world()
    status = _start(run, scope)
    assert fake.created == [] and status["results"]["not_reviewed"] == 1
    assert claude_spend.NOT_APPROVED_WORDS in status["plain"]


def test_a_second_review_of_the_same_text_is_answered_from_the_cache_at_no_cost(fake):
    fake.answer = lambda text: QUOTED
    sub, run, scope = _world()
    first = _start(run, scope)
    assert first["calls"] == 1
    again = _second_run(sub, scope)
    second = _start(again, scope)
    assert len(fake.created) == 1 and second["cache_hits"] == 1 and second["calls"] == 0
    assert second["verified"] == 1 and second["usd"]["charged"] == 0
    assert "1 answered from stored answers" in second["plain"]


# ------------------------------------------------------------- privacy of the record


def test_no_document_text_reaches_the_log_the_status_or_the_ledger(fake, caplog):
    fake.answer = lambda text: QUOTED
    _sub, run, scope = _world()
    with caplog.at_level(logging.DEBUG):
        status = _start(run, scope)
    held = json.dumps(status) + caplog.text
    held += Path(settings.claude_spend_log).read_text(encoding="utf-8")
    assert "Safety Department" not in held and REQ_CHAIR not in held


def test_the_close_removes_the_raw_answers(fake):
    fake.answer = lambda text: QUOTED
    _sub, run, scope = _world()
    _start(run, scope)
    assert _batch_rows("claude_batch_answers", run) == 0
    conn = db.connect()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM claude_batch_requests WHERE answer IS NOT NULL"
        ).fetchone()[0]
        == 0
    )


def test_a_deleted_submittal_takes_its_raw_answers_while_a_batch_is_out(fake):
    fake.ended = False
    sub, run, scope = _world()
    _start(run, scope)
    conn = db.connect()
    assert _batch_rows("claude_batch_requests", run) == 1
    with conn:
        document_refs.forget_quotes(conn, sub)
    assert _batch_rows("claude_batch_requests", run) == 0


def test_a_cancelled_run_stops_polling_and_keeps_no_answer(fake):
    fake.ended = False
    _sub, run, scope = _world()
    _start(run, scope)
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET status = 'cancelled' WHERE id = ?", (run,))
    fake.ended = True
    assert clause_review_claude.tick(run) is None and _rows(run) == []
    row = (
        db.connect()
        .execute(
            "SELECT state FROM clause_review_batches WHERE review_run_id = ?", (run,)
        )
        .fetchone()
    )
    assert row["state"] == clause_review_claude.CLOSED


def test_counts_that_do_not_add_up_say_so():
    status = {
        "pages": 1, "not_reviewed": [], "failed": [], "stopped": None, "requirements": 3, "verified": 1,
        "no_evidence": 0, "unverified": 0, "unreadable": 0, "kind": "procedure", "kind_state": "confirmed",
    }  # fmt: skip
    clause_review_status.fill(status, 1.0)
    assert status["results"]["adds_up"] is False
    assert "THE COUNTS DO NOT ADD UP" in status["plain"]


# --------------------------------------------------------------- the local engine


def _local(run, scope, reqs=None):
    return clause_review.run(
        run, allowed_document_ids=scope, provider=Fake({"HAZOP": NO_EVIDENCE})
    )


def test_the_local_limit_stays_and_prints_how_many_and_why_with_the_denominator(on):
    _sub, run, scope = _world(_reqs(65))
    status = _local(run, scope)
    assert len(_rows(run)) == 60 and status["over_limit"] == 5
    assert (
        "5 of 65 applicable requirement(s) not AI-reviewed: 5 over the local engine's limit of 60 per run"
        in status["plain"]
    )
    assert "not chosen by importance" in status["plain"]
    assert status["results"]["reviewed"] == 60 and status["results"]["adds_up"]
    assert "only the first 60" in status["stopped"]


def test_the_limit_line_reaches_the_crs_and_the_audit(on, monkeypatch):
    _sub, run, scope = _world(_reqs(61))
    plain = _local(run, scope)["plain"]
    _r, meta, _n, _s = main_mod._crs_content(
        run, access.unrestricted_scope(), "internal"
    )
    assert any(
        "1 of 61 applicable requirement(s) not AI-reviewed" in n["detail"]
        for n in meta["review_notes"]
    )
    assert "REVIEW INCOMPLETE" in meta["incomplete_notice"]
    audit = review_audit.build(run, access.unrestricted_scope(), None)
    assert plain in review_audit.render_markdown(audit)
    [step] = [s for s in audit["ai_use"]["steps"] if s["name"] == "clause_review"]
    assert step["results"]["not_reviewed"] == 1


def test_a_time_budget_and_the_limit_are_each_counted(on, monkeypatch):
    from tests.test_1477_clause_review import Clock

    monkeypatch.setattr(settings, "clause_review_seconds_per_page", 10.0)
    monkeypatch.setattr(settings, "clause_review_max_requirements", 3)
    _sub, run, scope = _world(_reqs(5))
    clock = Clock()
    status = clause_review.run(
        run, allowed_document_ids=scope, provider=Fake({"HAZOP": NO_EVIDENCE}, clock, step=20.0),
        clock=clock,
    )  # fmt: skip
    assert "4 of 5 applicable" in status["plain"]
    assert "2 over the local engine's limit of 3" in status["plain"]
    assert "2 because the time budget" in status["plain"]


def test_an_unreadable_answer_alone_still_marks_the_review_unfinished(on):
    _sub, run, scope = _world()
    with db.connect() as conn:
        conn.execute("UPDATE document_kinds SET state = 'confirmed'")
    clause_review.run(
        run, allowed_document_ids=scope, provider=Fake({"HAZOP": "not json"})
    )
    ai = clause_review._stored_ai_status(db.connect(), run)
    parts = absence.unchecked_parts(run_status="completed", outcome={}, ai_status=ai)
    assert any(p["part"] == "clause_review" for p in parts)
    assert "1 with an unreadable answer" in ai["clause_review"]["plain"]
