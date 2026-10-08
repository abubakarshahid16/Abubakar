"""P1: the labelled question set blocks a change that lowers the score.

The set (eval/p1/questions.json) is 30 invented-name questions run through the
real chat on an invented seven-document corpus, no model call. A question that
passes in eval/p1/baseline.json must keep passing, and no unanswerable
question may start getting an answer. The score may rise; it may not fall.

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


def test_the_score_has_not_dropped_on_the_invented_corpus(temp_storage):
    harness.ingest_corpus(temp_storage / "corpus")
    rows = harness.run_questions(harness.load_questions())
    reasons = harness.compare_with_baseline(rows, harness.load_baseline())
    assert reasons == [], "\n".join(reasons)
