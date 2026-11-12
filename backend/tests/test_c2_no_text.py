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


NO_TEXT = "This paper has no readable text in the library. Check its status on the Documents screen"
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


def test_a_paper_with_no_text_makes_no_call_of_any_kind_not_even_the_read_step(
    client, monkeypatch
):
    def never(*_a):
        raise AssertionError("the read step (it can call a reader) must not run")

    monkeypatch.setattr(nothing_read, "read_phase", never)
    fake = agent_review_jobs.lane()[0]
    with db.connect() as conn:
        conn.execute("DELETE FROM pages WHERE document_id = ?", (s.PAPER,))
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (s.PAPER,))
    run_id = _run(client)
    assert fake.kinds == []
    assert _summary(client, run_id)["stop_reason"].startswith("no_paper_text: ")
    assert "nothing was sent" not in _summary(client, run_id)["stop_reason"]


def test_nothing_read_on_a_paper_with_text_but_no_chunks_becomes_the_not_indexed_stop(
    client, monkeypatch
):
    def nothing(*_a):
        raise nothing_read.NothingRead("nothing read: the document could not be read")

    monkeypatch.setattr(nothing_read, "read_phase", nothing)
    with db.connect() as conn:
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (s.PAPER,))
    run_id = _run(client)
    assert _summary(client, run_id)["stop_reason"].startswith(
        "paper_text_not_indexed: "
    )


@pytest.mark.parametrize("status", ["queued", "extracting", "chunking"])
def test_a_paper_still_being_read_in_says_wait_not_no_text(client, status):
    with db.connect() as conn:
        conn.execute("UPDATE documents SET status = ? WHERE id = ?", (status, s.PAPER))
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (s.PAPER,))
    run_id = _run(client)
    got = _summary(client, run_id)
    assert got["paper_text"]["state"] == "still reading"
    assert (
        "still being read in: try again when its status is ready" in got["stop_reason"]
    )
    assert "no readable text" not in got["stop_reason"]


def test_a_ready_paper_with_text_is_not_called_still_reading(client):
    assert _state().state == "readable"  # the status check never touches a ready paper


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


# ---------------------------------------------------------------- the listing is true in every case; the general path lists too


def test_the_partly_readable_sentence_says_nothing_about_rules_so_it_is_true_when_none_were_asked(
    client, monkeypatch
):
    monkeypatch.setattr(
        agent_review_kind, "decide", lambda *_a, **_k: reading("unknown", known=False)
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages(document_id, page_no, text, char_count, needs_ocr, batch_no) VALUES (?,2,'',0,1,0)",
            (s.PAPER,),
        )
    run_id = _run(client)
    got = _summary(client, run_id)
    assert got["counts_by_class"] == {} and got["stop_reason"]  # nothing was asked
    sentence = got["paper_text"]["sentence"]
    assert sentence == "1 of 2 pages of this paper have no readable text (page 2)."
    assert "rules were asked" not in sentence


def test_a_partly_readable_general_review_paper_lists_its_unread_pages_too(
    client, monkeypatch
):
    def fake_general(run_id, submittal, *_a, **_k):
        with db.connect() as conn:  # what the real general job's finish writes
            conn.execute(
                "INSERT OR REPLACE INTO agent_review_run (run_id, submittal_document_id, paper_kind, kind_source, started_at)"
                " VALUES (?,?,?,?,?)",
                (run_id, submittal, "procedure", "x", "2020-01-01"),
            )
        return {"counts": {}, "stop_reason": None, "usd": None, "partial": False}

    monkeypatch.setattr(agent_review_jobs.general_job, "run", fake_general)
    monkeypatch.setattr(
        agent_review_kind, "decide", lambda *_a, **_k: reading("procedure")
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages(document_id, page_no, text, char_count, needs_ocr, batch_no) VALUES (?,2,'',0,1,0)",
            (s.PAPER,),
        )
    run_id = _run(client)
    got = (
        db.connect()
        .execute(
            "SELECT json_extract(equipment_json, '$.paper_text.pages_not_read') FROM agent_review_run WHERE run_id = ?",
            (run_id,),
        )
        .fetchone()[0]
    )
    assert got == "[2]"


# ---------------------------------------------------------------- a plan with nothing to ask is NEVER silent (property)


def _empty_doc(rows, counts, books=None):
    doc, _cache = s.item_doc()
    return {
        **doc,
        "items": [],
        "counts": {"skill": 0, "rule": 0},
        "rule_labels": {
            "on": True,
            "paper_kind": "datasheet",
            "paper_kind_known": True,
            "counts": counts,
            "left_out": [],
            "summary_lines": [],
            "missing_rule_books": [],
            "candidates": {
                "source": "the rules of the selected books",
                "rows": rows,
                "repeats": 0,
                "books_included": books,
                "books_not_selected": {"books": 0, "ai_approved_of_this_kind": 0},
            },
        },
    }


def _way_no_text(client, monkeypatch):
    with db.connect() as conn:
        conn.execute("DELETE FROM pages WHERE document_id = ?", (s.PAPER,))


def _way_not_indexed(client, monkeypatch):
    with db.connect() as conn:
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (s.PAPER,))


def _way_still_reading(client, monkeypatch):
    with db.connect() as conn:
        conn.execute(
            "UPDATE documents SET status = 'chunking' WHERE id = ?", (s.PAPER,)
        )
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (s.PAPER,))


def _way_kind_unknown(client, monkeypatch):
    monkeypatch.setattr(
        agent_review_kind, "decide", lambda *_a, **_k: reading("unknown", known=False)
    )


def _way_kind_not_enabled(client, monkeypatch):
    monkeypatch.setattr(
        agent_review_kind, "decide", lambda *_a, **_k: reading("drawing")
    )


def _way_book_pages_missing(client, monkeypatch):
    with db.connect() as conn:
        conn.execute("DELETE FROM pages WHERE document_id = ?", (s.STD,))


def _way_builder(rows, counts, books=None):
    def way(client, monkeypatch):
        doc = _empty_doc(rows, counts, books)
        monkeypatch.setattr(items_mod, "build_items_for_run", lambda *_a, **_k: doc)

    return way


WAYS = {
    "no text": _way_no_text,
    "not indexed": _way_not_indexed,
    "still reading": _way_still_reading,
    "kind unknown": _way_kind_unknown,
    "kind not enabled": _way_kind_not_enabled,
    "rule book pages missing (preflight refuses)": _way_book_pages_missing,
    "no rows from the selected books": _way_builder(0, {}, 0),
    "selected books hold no rules": _way_builder(0, {}, 2),
    "rows all left out": _way_builder(
        40, {"another_equipment_type": 25, "needs_a_human": 15}
    ),
    "empty plan, no counts at all": _way_builder(None, {}),
}


@pytest.mark.parametrize("way", sorted(WAYS))
def test_a_plan_with_nothing_to_ask_always_carries_a_plain_sentence_never_silent(
    client, monkeypatch, way
):
    WAYS[way](client, monkeypatch)
    fake = agent_review_jobs.lane()[0]
    run_id = _run(client)
    got = _summary(client, run_id)
    used = _rules_used(client, run_id)
    assert fake.kinds == []  # no AI call
    if (
        "preflight" not in way
    ):  # a refused plan keeps the rules it had chosen on the Rules used page
        assert used["asked"] == []
    stop = got["stop_reason"]
    assert stop and len(stop.split(": ", 1)[-1]) > 20, way  # never silent
    assert used["stop_reason"] == stop  # the Rules used page says it too


@pytest.mark.parametrize(
    "way,needle",
    [
        (
            "no rows from the selected books",
            "no rule book was selected for this paper (counting only rule books its reader may read)",
        ),
        ("rows all left out", "40 stored rules were looked at and 0 fit this paper"),
        ("empty plan, no counts at all", "the plan recorded no further cause"),
    ],
)
def test_the_causes_of_an_empty_plan_are_each_worded_from_what_the_plan_knows(
    client, monkeypatch, way, needle
):
    WAYS[way](client, monkeypatch)
    stop = _summary(client, _run(client))["stop_reason"]
    assert stop.startswith("no_rule_asked: ") and needle in stop
    if way == "rows all left out":
        assert (
            "another_equipment_type" not in stop
        )  # the plain left-out words, not the codes


def test_the_trial_checks_that_a_text_stop_is_true_of_the_copy_it_ran_on(client):
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "trial_on_copy.py"
    spec = importlib.util.spec_from_file_location("trial_on_copy_c2b", path)
    trial = importlib.util.module_from_spec(spec)
    sys.modules["trial_on_copy_c2b"] = trial
    spec.loader.exec_module(trial)
    run_id = _run(client)  # a readable paper: the run asks rules
    with db.connect() as conn:
        conn.execute(
            "UPDATE agent_review_run SET stop_reason = 'no_paper_text: x' WHERE run_id = ?",
            (run_id,),
        )
        lying = trial.stop_is_true_check(conn, run_id, "no_paper_text: x")
        conn.execute("DELETE FROM pages WHERE document_id = ?", (s.PAPER,))
        honest = trial.stop_is_true_check(conn, run_id, "no_paper_text: x")
    assert [c.ok for c in lying] == [False] and [c.ok for c in honest] == [True]


def test_no_book_and_books_with_no_rules_are_two_different_true_sentences(client):
    from app import agent_review_text as t

    plan = lambda books: {  # noqa: E731
        "items": [],
        "block": {"candidates": {"rows": 0, "books_included": books}, "counts": {}},
    }
    none, one, many = (t.empty_plan_sentence(plan(b)) for b in (0, 1, 3))
    assert "no rule book was selected" in none and "hold" not in none
    assert "1 rule book was selected" in one and "holds 0 stored rules" in one
    assert "3 rule books were selected" in many and "hold 0 stored rules" in many
    assert (
        "may read" in none and "may read" in one and "may read" in many
    )  # the boundary is in the words


def test_books_included_counts_only_books_the_reader_may_read(client):
    from app import agent_review_text as t

    with db.connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS review_applicable_standards (review_run_id TEXT, standard_document_id TEXT, included INTEGER)"
        )
        conn.executemany(
            "INSERT INTO review_applicable_standards VALUES ('r', ?, ?)",
            [("b1", 1), ("b2", 1), ("b3", 0)],
        )
        assert (
            t.books_included(conn, "r", {"b1", "b3"}) == 1
        )  # b2 unreadable, b3 not included
        assert t.books_included(conn, "r", {"b1", "b2"}) == 2


def test_a_general_review_with_no_line_and_no_stop_gets_its_own_true_sentence(
    client, monkeypatch
):
    def fake_general(run_id, submittal, *_a, **_k):
        with db.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO agent_review_run (run_id, submittal_document_id, paper_kind, kind_source, started_at)"
                " VALUES (?,?,?,?,?)",
                (run_id, submittal, "procedure", "x", "2020-01-01"),
            )
        return {
            "counts": {"lines": 0},
            "stop_reason": None,
            "usd": None,
            "partial": False,
        }

    monkeypatch.setattr(agent_review_jobs.general_job, "run", fake_general)
    monkeypatch.setattr(
        agent_review_kind, "decide", lambda *_a, **_k: reading("procedure")
    )
    run_id = _run(client)
    stop = _summary(client, run_id)["stop_reason"]
    assert (
        stop
        == "no_rule_asked: The general review wrote no line for this paper and recorded no cause."
    )


def test_a_general_review_that_wrote_lines_or_gave_a_cause_is_left_alone(client):
    from app import agent_review_text as t

    run_id = _run(client)
    for counts, stop in (({"lines": 3}, None), ({"lines": 0}, "refused: x")):
        result = {"counts": counts, "stop_reason": stop}
        with db.connect() as conn:
            t.record_general(conn, run_id, t.read(conn, s.PAPER), result)
        assert result["stop_reason"] == stop


def test_the_trial_fails_on_the_fallback_sentence_and_passes_on_a_real_cause(
    client, monkeypatch
):
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "trial_on_copy.py"
    spec = importlib.util.spec_from_file_location("trial_on_copy_c2c", path)
    trial = importlib.util.module_from_spec(spec)
    sys.modules["trial_on_copy_c2c"] = trial
    spec.loader.exec_module(trial)
    name = "rules asked > 0, or the plan says why none"
    for way, ok in (
        ("empty plan, no counts at all", False),
        ("no rows from the selected books", True),
    ):
        WAYS[way](client, monkeypatch)
        run_id = _run(client)
        checks = trial.rules_check(
            db.connect(), run_id, _rules_used(client, run_id), False
        )
        got = next(c for c in checks if c.name == name)
        assert got.ok is ok, (way, got.detail)
        with db.connect() as conn:
            conn.execute("UPDATE review_runs SET status = 'completed'")
