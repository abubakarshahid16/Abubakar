"""C2 (order 13, owner point 12): a paper with no stored text says so, and is never asked 0 rules in silence.

Invented papers and an invented model; no network. Each test fails without the change: delete the text check in
`agent_review_jobs.run` and the paper is asked 0 rules with no word (or a kind question, or a retried failure)."""

from __future__ import annotations

import sys

import pytest

from app import agent_review_items as items_mod
from app import (
    agent_review_jobs,
    agent_review_kind,
    agent_review_text,
    db,
    nothing_read,
)
from tests import agent_review_support as s
from tests.test_agent_review_job import reading, run_job, start
from tests.test_agent_review_routes import (
    client as _routes_client,  # noqa: F401 - the same invented world, with the routes
)


@pytest.fixture
def client(_routes_client):  # noqa: F811 - a fixture takes the imported fixture by name
    return _routes_client


NO_TEXT = (
    "This paper has no readable text in the library: re-read it, then review again."
)
NOT_INDEXED = "This paper's text is stored but not indexed for search"


def _run(client, *, expect="done"):
    run_id, job_id = start()
    assert run_job(job_id) == expect
    return run_id


def _summary(client, run_id):
    r = client.get(f"/api/reviews/runs/{run_id}/agent/summary")
    assert r.status_code == 200, r.text
    return r.json()


def _rules_used(client, run_id):
    r = client.get(f"/api/reviews/runs/{run_id}/rules-used")
    assert r.status_code == 200, r.text
    return r.json()


def _no_call_made(monkeypatch):
    """The item builder must not even be reached for a paper with no text."""
    reached = []
    real = items_mod.build_items

    def spy(*a, **k):
        reached.append(1)
        return real(*a, **k)

    monkeypatch.setattr(items_mod, "build_items", spy)
    return reached


# ---------------------------------------------------------------- the state, by itself


def _state(paper=s.PAPER):
    return agent_review_text.read(db.connect(), paper)


def test_a_paper_with_no_page_row_has_no_text(client):
    with db.connect() as conn:
        conn.execute("DELETE FROM pages WHERE document_id = ?", (s.PAPER,))
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (s.PAPER,))
    got = _state()
    assert got.state == "no text" and got.sentence.startswith(NO_TEXT)
    assert got.stop_code == "no_paper_text" and got.stop.startswith("no_paper_text: ")


def test_pages_with_only_blank_text_have_no_text_and_every_page_is_listed(client):
    with db.connect() as conn:
        conn.execute("UPDATE documents SET page_count = 3 WHERE id = ?", (s.PAPER,))
        conn.execute(
            "UPDATE pages SET text = '  \n ', char_count = 0 WHERE document_id = ?",
            (s.PAPER,),
        )
    got = _state()
    assert (
        got.state == "no text"
        and got.pages_total == 3
        and got.pages_not_read == [1, 2, 3]
    )


def test_text_pages_but_no_chunks_is_not_indexed(client):
    with db.connect() as conn:
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (s.PAPER,))
    got = _state()
    assert got.state == "not indexed" and got.sentence.startswith(NOT_INDEXED)
    assert got.stop_code == "paper_text_not_indexed"


def test_one_readable_and_one_unreadable_page_is_partly_readable_and_lists_the_page(
    client,
):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages(document_id, page_no, text, char_count, needs_ocr, batch_no) VALUES (?,2,'',0,1,0)",
            (s.PAPER,),
        )
    got = _state()
    assert got.state == "partly readable" and got.stop is None
    assert got.pages_not_read == [2] and got.pages_total == 2
    assert "page 2" in got.sentence and "1 of 2 pages" in got.sentence


def test_a_page_the_file_has_but_the_library_holds_no_row_for_is_listed_as_not_read(
    client,
):
    with db.connect() as conn:
        conn.execute("UPDATE documents SET page_count = 3 WHERE id = ?", (s.PAPER,))
    got = _state()
    assert (
        got.state == "partly readable"
        and got.pages_not_read == [2, 3]
        and "pages 2, 3" in got.sentence
    )


def test_a_fully_readable_paper_has_no_sentence(client):
    got = _state()
    assert (got.state, got.sentence, got.pages_not_read, got.stop) == (
        "readable",
        None,
        [],
        None,
    )


# ---------------------------------------------------------------- the run, the screen routes


@pytest.mark.parametrize("how", ["no_pages", "blank_pages"])
def test_no_text_stops_before_any_rule_or_call_and_says_so_everywhere(
    client, monkeypatch, how
):
    with db.connect() as conn:
        if how == "no_pages":
            conn.execute("DELETE FROM pages WHERE document_id = ?", (s.PAPER,))
        else:
            conn.execute(
                "UPDATE pages SET text = '', char_count = 0 WHERE document_id = ?",
                (s.PAPER,),
            )
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (s.PAPER,))
    reached = _no_call_made(monkeypatch)
    fake = agent_review_jobs.lane()[0]
    run_id = _run(client)
    assert reached == [] and fake.kinds == []  # no rule chosen, no AI call
    run = _summary(client, run_id)
    assert run["stop_reason"].startswith("no_paper_text: " + NO_TEXT)
    assert run["paper_text"]["state"] == "no text" and run["paper_text"][
        "sentence"
    ].startswith(NO_TEXT)
    assert run["counts_by_class"] == {} and run["usd"] is None
    used = _rules_used(client, run_id)
    assert used["asked"] == [] and used["stop_reason"] == run["stop_reason"]
    assert used["paper_text"]["sentence"].startswith(NO_TEXT)
    status = (
        db.connect()
        .execute("SELECT status FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()[0]
    )
    assert (
        status == "completed"
    )  # a stopped run is a finished run with its reason, not a retried failure


def test_a_paper_with_text_but_no_chunks_stops_with_its_own_sentence(
    client, monkeypatch
):
    with db.connect() as conn:
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (s.PAPER,))
    reached = _no_call_made(monkeypatch)
    run_id = _run(client)
    assert reached == []
    run = _summary(client, run_id)
    assert run["stop_reason"].startswith("paper_text_not_indexed: " + NOT_INDEXED)
    assert run["paper_text"]["state"] == "not indexed"
    assert _rules_used(client, run_id)["paper_text"]["state"] == "not indexed"


def test_the_trials_own_plan_check_counts_the_stop_as_the_plan_saying_why(client):
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "trial_on_copy.py"
    spec = importlib.util.spec_from_file_location("trial_on_copy_c2", path)
    trial = importlib.util.module_from_spec(spec)
    sys.modules["trial_on_copy_c2"] = (
        trial  # a dataclass in the module looks itself up here
    )
    spec.loader.exec_module(trial)
    with db.connect() as conn:
        conn.execute("DELETE FROM pages WHERE document_id = ?", (s.PAPER,))
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (s.PAPER,))
    run_id = _run(client)
    checks = trial.rules_check(db.connect(), run_id, _rules_used(client, run_id), False)
    got = next(
        c for c in checks if c.name == "rules asked > 0, or the plan says why none"
    )
    assert got.ok and "the plan stopped: no_paper_text" in got.detail


def test_nothing_read_from_the_read_step_becomes_the_same_stop_not_a_retried_failure(
    client, monkeypatch
):
    def nothing(*_a):
        raise nothing_read.NothingRead(
            "nothing read: the document could not be read (2 pages, 0 values)"
        )

    monkeypatch.setattr(nothing_read, "read_phase", nothing)
    with db.connect() as conn:
        conn.execute("DELETE FROM pages WHERE document_id = ?", (s.PAPER,))
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (s.PAPER,))
    run_id = _run(client)
    assert _summary(client, run_id)["stop_reason"].startswith("no_paper_text: ")


def test_a_read_step_that_found_nothing_on_a_paper_that_has_text_is_still_a_loud_failure(
    client, monkeypatch
):
    def nothing(*_a):
        raise nothing_read.NothingRead(
            "nothing read: the document could not be read (1 page, 0 values)"
        )

    monkeypatch.setattr(nothing_read, "read_phase", nothing)
    run_id, job_id = start()
    assert run_job(job_id) != "done"  # never completed as if it were reviewed
    assert (
        db.connect()
        .execute("SELECT 1 FROM agent_review_line WHERE run_id = ?", (run_id,))
        .fetchone()
        is None
    )


def test_a_partly_readable_paper_is_reviewed_and_its_unreadable_pages_are_listed(
    client,
):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages(document_id, page_no, text, char_count, needs_ocr, batch_no) VALUES (?,2,'',0,1,0)",
            (s.PAPER,),
        )
    run_id = _run(client)
    run = _summary(client, run_id)
    assert run["counts_by_class"]  # it ran: lines were written
    assert run["paper_text"]["state"] == "partly readable" and run["paper_text"][
        "pages_not_read"
    ] == [2]
    assert "page 2" in run["paper_text"]["sentence"]
    used = _rules_used(client, run_id)
    assert used["asked"] and used["paper_text"]["pages_not_read"] == [2]


def test_a_readable_paper_records_readable_and_no_sentence(client):
    run_id = _run(client)
    got = _summary(client, run_id)["paper_text"]
    assert (got["state"], got["sentence"], got["pages_not_read"]) == (
        "readable",
        None,
        [],
    )


# ---------------------------------------------------------------- the start route


def test_a_no_text_paper_of_unknown_kind_is_queued_and_stopped_with_the_text_sentence_not_a_409_about_kind(
    client, monkeypatch
):
    monkeypatch.setattr(
        agent_review_kind, "decide", lambda *_a, **_k: reading("unknown", known=False)
    )
    with db.connect() as conn:
        conn.execute("DELETE FROM pages WHERE document_id = ?", (s.PAPER,))
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (s.PAPER,))
    r = client.post("/api/reviews/agent-run", json={"submittal_document_id": s.PAPER})
    assert r.status_code == 200, r.text
    job_id = agent_review_jobs.claim_next("w-test")
    assert agent_review_jobs.run(job_id, "w-test") == "done"
    run_id = r.json().get("run_id") or r.json()["review_run_id"]
    assert _summary(client, run_id)["stop_reason"].startswith("no_paper_text: ")


def test_a_paper_WITH_text_of_unknown_kind_is_still_a_409_kind_refusal(
    client, monkeypatch
):
    monkeypatch.setattr(
        agent_review_kind, "decide", lambda *_a, **_k: reading("unknown", known=False)
    )
    r = client.post("/api/reviews/agent-run", json={"submittal_document_id": s.PAPER})
    assert r.status_code == 409


def test_a_general_review_paper_with_text_but_no_chunks_is_not_stopped_but_with_no_text_it_is(
    client, monkeypatch
):
    called = []

    def fake_general(run_id, submittal, *_a, **_k):
        called.append(submittal)
        return {"counts": {}, "stop_reason": None, "usd": None, "partial": False}

    monkeypatch.setattr(agent_review_jobs.general_job, "run", fake_general)
    monkeypatch.setattr(
        agent_review_kind, "decide", lambda *_a, **_k: reading("procedure")
    )
    with db.connect() as conn:
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (s.PAPER,))
    _run(client)
    assert called == [
        s.PAPER
    ]  # it reads the page text itself: the missing chunks do not stop it
    with db.connect() as conn:
        conn.execute("DELETE FROM pages WHERE document_id = ?", (s.PAPER,))
    run_id = _run(client)
    assert called == [s.PAPER]  # no text: stopped before the general review
    assert _summary(client, run_id)["stop_reason"].startswith("no_paper_text: ")
