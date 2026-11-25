"""D2 (planner 26 Nov 2026 03:35): a read or check step of the general review that catches a fault so the review goes on is
REPORTED: one row of the run's calls ("<what> not applied: <class>", no model, no cost), and its plain sentence on the page and in
the team file ("Steps that did not run"). One test per step. Invented papers and messages; no paid call, no socket."""

from __future__ import annotations

import contextvars
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app import aim_review, aim_review_completeness, aim_review_view
from app.aim_review import always as A
from app.aim_review import book_names as BN
from app.aim_review import contract_code as CC
from app.aim_review import engine as E
from app.aim_review import faults
from app.aim_review import unread as U
from app.aim_review.paper import Paper
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    PAPER,
    MemoryStore,
    open_aim_db,
)

#: A fault whose message quotes a paper: the row keeps its class only.
SECRET = "invented paper words that must never be stored"


class Boom(RuntimeError):
    pass


def boom(*_a, **_k):
    raise Boom(SECRET)


@pytest.fixture
def calls():
    got: list = []
    with faults.recording(got):
        yield got


def _rows(calls) -> list[dict]:
    return [c.as_dict() if hasattr(c, "as_dict") else c for c in calls]


def _only(calls, step: str) -> dict:
    rows = [r for r in _rows(calls) if r["step"] == step]
    assert len(rows) == 1, _rows(calls)
    return rows[0]


def _said(calls, step: str) -> str:
    """The plain sentence the page and the team file print for this step."""
    got = {x["step"]: x for x in aim_review_view.steps_not_applied(_rows(calls))}
    assert step in got, _rows(calls)
    sentence = got[step]["sentence"]
    assert not sentence.startswith("The step "), "each step has its own plain words"
    return sentence


# ---- the recorder ---------------------------------------------------------------------------------------------------------


def test_a_fault_is_a_failed_row_of_the_run_with_its_class_only(calls):
    faults.record("aim_g1_facts", "the library facts for G1", Boom(SECRET))
    row = _only(calls, "aim_g1_facts")
    assert (row["ok"], row["model"], row["usd"]) == (False, "code", 0.0)
    assert row["code"] == "the library facts for G1 not applied: Boom"
    assert SECRET not in json.dumps(_rows(calls))


def test_outside_a_run_a_fault_is_only_logged(caplog):
    faults.record(
        "aim_g1_facts", "the library facts for G1", Boom(SECRET)
    )  # no run bound: nothing to append to, no raise
    assert (
        "the library facts for G1 not applied (Boom)" in caplog.text
        and SECRET not in caplog.text
    )


def test_a_fault_in_a_judge_worker_thread_reaches_the_run(calls):
    """The judge runs side by side (`aim_review.parallel` copies the context into each worker): a fault there is recorded too."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        pool.submit(
            contextvars.copy_context().run, faults.record, "aim_contract_code", "x", "y"
        ).result()
    assert _only(calls, "aim_contract_code")["code"] == "x not applied: y"


# ---- one test per step ----------------------------------------------------------------------------------------------------


def test_the_unread_pages_check_that_fails_is_reported_and_never_reads_as_all_read(
    calls, monkeypatch
):
    monkeypatch.setattr(U, "_ref", boom)
    paper = U.with_unread(
        None, "doc_d2", Paper("doc_d2", {1: "invented page text " * 3}), None
    )
    assert paper.unread_checked is False
    record = [c.as_dict() for c in U.read_calls(paper)]
    assert U.record_state(record) == U.NOT_RECORDED  # never "every page read"
    assert (
        _only(calls, U.CHECK_STEP)["code"] == "the unread-pages check not applied: Boom"
    )
    assert "do not take every page as read" in _said(calls, U.CHECK_STEP)


def test_stored_picture_readings_that_cannot_be_read_are_reported_but_an_older_database_is_not(
    calls, monkeypatch, tmp_path
):
    from app import docx_reader, word_pictures
    from app.config import settings
    from app.docx_pages import PICTURE_IMAGE

    pic = type("Pic", (), {"kind": PICTURE_IMAGE, "no": 1})()
    monkeypatch.setattr(
        docx_reader,
        "read_structure",
        lambda *a, **k: type("S", (), {"pictures": [pic]})(),
    )
    monkeypatch.setattr(word_pictures, "_sha256", lambda p: "0" * 64)
    monkeypatch.setattr(settings, "word_page_markers_enabled", True)

    class Conn:
        def __init__(self, exc):
            self.exc = exc

        def execute(self, *_a):
            raise self.exc

    old = U._word_unread(
        Conn(sqlite3.OperationalError("no such table: word_picture_readings")),
        tmp_path / "a.docx",
    )
    assert [x["why"] for x in old] == [U.PICTURE_NOT_READ] and calls == []
    locked = U._word_unread(
        Conn(sqlite3.OperationalError("database is locked")), tmp_path / "a.docx"
    )
    assert [x["why"] for x in locked] == [
        U.PICTURE_NOT_READ
    ]  # every picture still named as not read
    assert _only(calls, U.PICTURES_STEP)["code"].endswith(
        "not applied: OperationalError"
    )
    assert "every picture is named as not read" in _said(calls, U.PICTURES_STEP)


def test_a_contract_code_check_that_fails_is_reported_by_its_name(calls, monkeypatch):
    def check_terms(_pages):  # the check's own name is what the row names
        raise Boom(SECRET)

    monkeypatch.setattr(CC, "check_terms", check_terms)
    CC.lines({1: "invented contract page"}, {"kind": "contract"}, None)
    row = _only(calls, "aim_contract_code")
    assert row["code"] == "a contract code check not applied: check_terms: Boom"
    assert "(check_terms: Boom)" in _said(calls, "aim_contract_code")


def test_the_packages_schedules_that_cannot_be_read_are_reported(calls, monkeypatch):
    from app.aim_review import references

    monkeypatch.setattr(references, "held_schedules", boom)
    assert CC.held_labels(None, "doc_d2") is None
    assert _only(calls, "aim_contract_schedules")["code"].endswith("not applied: Boom")
    assert "no line about the package's Schedules" in _said(
        calls, "aim_contract_schedules"
    )


def test_g1_library_facts_that_cannot_be_read_are_reported(calls, monkeypatch):
    from app.aim_review import library as L

    monkeypatch.setattr(L, "library", boom)
    assert A._library_facts(None, {"equipment_type": None}, frozenset(), {1: "x"}) == (
        "",
        {},
    )
    assert (
        _only(calls, "aim_g1_facts")["code"]
        == "the library facts for G1 not applied: Boom"
    )
    assert "G1 was judged on the paper alone" in _said(calls, "aim_g1_facts")


def test_the_tables_reasons_for_the_rule_books_that_cannot_be_read_are_reported(
    calls, monkeypatch
):
    from app.aim_review import checklist as CL

    monkeypatch.setattr(CL, "wanted", boom)
    assert BN.fallback_reasons(None, "doc_d2", {}, frozenset(), frozenset()) == {}
    assert _only(calls, "aim_book_reasons")["code"].endswith("not applied: Boom")
    assert "the reason was not recorded" in _said(calls, "aim_book_reasons")


def test_a_list_of_saved_checklists_that_cannot_be_read_is_reported(calls):
    store = type("Store", (), {"keys": staticmethod(boom)})()
    assert E._known_keys(store) == []
    assert _only(calls, "aim_checklist_keys")["code"].endswith("not applied: Boom")
    assert "without the saved checklist types" in _said(calls, "aim_checklist_keys")


# ---- through a whole run: the engine binds the recorder, the result keeps the rows --------------------------------------------


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


def test_through_a_run_a_checklist_not_saved_and_g1_facts_not_read_are_rows_of_the_result(
    aim_db, monkeypatch
):
    from app import cited_edition

    monkeypatch.setattr(MemoryStore, "put", boom)
    monkeypatch.setattr(cited_edition, "cited_years", boom)
    r = aim_review.run(aim_db, run_id="run_d2", paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}), store=MemoryStore(),
                       max_usd=5.0, model=E.FakeModel(kind="datasheet", subject_key="test_item"))  # fmt: skip
    assert r.status == "done", r.stop_reason  # the review goes on
    assert r.checklist_sha256 == ""
    steps = {x["step"]: x for x in aim_review_view.steps_not_applied(r.calls)}
    assert {"aim_checklist_save", "aim_g1_facts"} <= set(steps)
    assert steps["aim_checklist_save"]["sentence"].startswith(
        "The checklist was not saved for reuse (Boom)"
    )
    assert SECRET not in json.dumps(r.calls)
    with faults.recording([]) as after:  # the run unbound its list when it ended
        pass
    assert after == []


def test_a_run_where_every_step_ran_reports_none():
    assert (
        aim_review_view.steps_not_applied(
            [{"step": "aim_judge", "ok": True, "code": ""}]
        )
        == []
    )


# ---- the count after the review ----------------------------------------------------------------------------------------------


def test_a_count_after_the_review_that_cannot_run_is_kept_with_the_run(monkeypatch):
    kept = {}
    from app import access

    monkeypatch.setattr(access, "unrestricted_scope", lambda: None)
    monkeypatch.setattr(aim_review_completeness, "verify", boom)
    monkeypatch.setattr(aim_review_completeness, "connect", lambda: None)
    monkeypatch.setattr(
        aim_review_completeness.aim_review_store,
        "set_completeness",
        lambda conn, run_id, rep: kept.update({run_id: rep}),
    )
    assert aim_review_completeness.record_after_run("run_d2") is None
    rep = kept["run_d2"]
    assert rep["ok"] is False and rep["check_failed"] == "Boom"
    assert rep["sentence"].startswith(
        "The count after the review could not run (Boom)."
    ) and SECRET not in json.dumps(rep)


# ---- the team file -----------------------------------------------------------------------------------------------------------


def test_the_team_file_row_is_named_for_every_step_not_only_ai_steps():
    from app import aim_review_sheet

    src = Path(aim_review_sheet.__file__).read_text(encoding="utf-8")
    assert (
        '"Steps that did not run"' in src and '"AI steps that did not run"' not in src
    )
