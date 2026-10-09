"""P1: the labelled question set blocks a change that lowers the score.

The set (eval/p1/questions.json, version 5) is 67 invented-name questions run
through the real chat on an invented fifteen-document corpus, no model call.
The gate (owner decision 2026-10-08, `gate` in eval/p1/baseline.json, raised
on 2026-10-09 to 44 of the 67 of version 5): at least 44 pass, and all 26 protected
questions still pass (the 23 version 1 passes, and P1-65, P1-66, P1-67). No unanswerable
question may start getting an answer.

Raise the bar after an improvement with:
    python eval/p1/run_p1.py --write-baseline
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "eval" / "p1"))

import harness

from app import access, db, keyword
from app.config import settings


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "p1.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield tmp_path
    db.reset_connection()


def test_every_label_is_true_of_the_invented_corpus():
    """A wrong label would blame the system for the author's mistake."""
    assert harness.check_labels(harness.load_questions()) == []


def _row(qid, passed, answerable=True, answered=True, clause_ok=None):
    return {"id": qid, "passed": passed, "answerable": answerable,
            "answered": answered, "clause_ok": clause_ok, "answer_type": "extract",
            "cited_document": None, "cited_pages": []}


BASE = {"passing": ["A", "B"], "clause_passing": ["A"], "failing_known": ["U"]}


def test_a_question_that_used_to_pass_and_now_fails_blocks():
    reasons = harness.compare_with_baseline(
        [_row("A", True, clause_ok=True), _row("B", False)], BASE)
    assert any(r.startswith("B passed") for r in reasons)


def test_a_citation_that_used_to_name_the_right_clause_blocks():
    reasons = harness.compare_with_baseline(
        [_row("A", True, clause_ok=False), _row("B", True)], BASE)
    assert any("right clause" in r for r in reasons)


def test_a_new_answer_to_an_unanswerable_question_blocks():
    rows = [_row("A", True, clause_ok=True), _row("B", True),
            _row("N", False, answerable=False, answered=True)]
    assert any(r.startswith("N is unanswerable") for r in harness.compare_with_baseline(rows, BASE))


def test_an_improvement_and_a_known_failure_do_not_block():
    rows = [_row("A", True, clause_ok=True), _row("B", True), _row("C", True),
            _row("U", False, answerable=False, answered=True)]
    assert harness.compare_with_baseline(rows, BASE) == []


GATED = {"passing": ["A", "B"], "clause_passing": ["A", "B"], "failing_known": [],
         "gate": {"min_passing": 2, "protected": ["A"]}}


def test_with_a_gate_an_unprotected_question_may_trade_places():
    """B passed in the baseline and fails now, C passes instead: the total
    holds and A (protected) holds, so the change is not blocked."""
    rows = [_row("A", True, clause_ok=True), _row("B", False, clause_ok=False),
            _row("C", True)]
    assert harness.compare_with_baseline(rows, GATED) == []


def test_with_a_gate_a_protected_question_that_fails_blocks():
    rows = [_row("A", False), _row("B", True), _row("C", True)]
    assert any(r.startswith("A passed") for r in harness.compare_with_baseline(rows, GATED))


def test_with_a_gate_a_total_below_the_minimum_blocks():
    rows = [_row("A", True, clause_ok=True), _row("B", False), _row("C", False)]
    reasons = harness.compare_with_baseline(rows, GATED)
    assert any("the gate needs at least 2" in r for r in reasons), reasons


def test_the_committed_gate_is_44_of_67_with_26_protected():
    """The README states this gate; the file it is enforced from must agree."""
    base = harness.load_baseline()
    gate = base["gate"]
    assert gate["min_passing"] == 44 and base["total"][1] == 67
    assert len(gate["protected"]) == 26
    originals = [q for q in gate["protected"] if int(q.split("-")[1]) <= 30]
    assert len(originals) == 23
    assert set(gate["protected"]) - set(originals) == {"P1-65", "P1-66", "P1-67"}
    assert set(gate["protected"]) <= set(base["passing"])


_MULTI = {"id": "M", "answerable": True, "expected_sources": [
    {"document": "STD-A-001.pdf", "pages": [3], "answer_contains": ["3.0 mm/s"]},
    {"document": "STD-K-010.pdf", "pages": [2], "answer_contains": ["6.0 mm/s"]}]}


def _passage(filename, page, text):
    return {"filename": filename, "page_start": page, "page_end": page,
            "text": text, "section": None}


def test_a_multi_document_answer_that_cites_only_one_side_fails():
    """Both figures are in the answer text, but only one document is cited:
    the reader cannot check the other figure, so it is not a pass."""
    one_side = {"answer_type": "extract", "answer": "3.0 mm/s and 6.0 mm/s",
                "answer_passages": [_passage("STD-A-001.pdf", 3, "3.0 mm/s RMS")]}
    both = {"answer_type": "extract", "answer": "",
            "answer_passages": [_passage("STD-A-001.pdf", 3, "3.0 mm/s RMS"),
                                _passage("STD-K-010.pdf", 2, "6.0 mm/s RMS.")]}
    assert harness.sources_ok(_MULTI, one_side) is False
    assert harness.sources_ok(_MULTI, both) is True
    assert harness._passed(_MULTI, {"sources_ok": True}) is True
    assert harness._passed(_MULTI, {"sources_ok": False}) is False


def test_a_multi_document_label_that_is_not_in_the_corpus_is_caught():
    wrong = {**_MULTI, "expected_sources": [
        _MULTI["expected_sources"][0],
        {"document": "STD-K-010.pdf", "pages": [2], "answer_contains": ["7.5 mm/s"]}]}
    problems = harness.check_labels([wrong])
    assert any("7.5 mm/s" in p for p in problems), problems
    assert harness.check_labels([_MULTI]) == []


def test_the_score_has_not_dropped_on_the_invented_corpus(temp_storage):
    harness.ingest_corpus(temp_storage / "corpus")
    rows = harness.run_questions(harness.load_questions())
    reasons = harness.compare_with_baseline(rows, harness.load_baseline())
    assert reasons == [], "\n".join(reasons)
