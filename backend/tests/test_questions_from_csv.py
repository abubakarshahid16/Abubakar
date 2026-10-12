"""The engineer's question sheet -> eval question set. Only verified lines
become questions; a verified line that cannot be scored is refused by line."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("questions_from_csv", REPO / "scripts" / "questions_from_csv.py")
q = importlib.util.module_from_spec(_spec)
sys.modules["questions_from_csv"] = q
_spec.loader.exec_module(q)


def _row(**kw):
    base = dict(id="R01", question="What is the minimum X?", answerable="true",
                expected_document="S.pdf", expected_pages="13", expected_clause="7.8",
                expected_answer_contains="3 | mm", source_line="", engineer_verified="yes", note="")
    base.update(kw)
    return base


def test_only_verified_lines_become_questions():
    data, counts = q.convert([(2, _row()), (3, _row(id="R02", engineer_verified=""))], "c", "a")
    assert [x["id"] for x in data["questions"]] == ["R01"]
    assert counts["unverified_skipped"] == 1
    assert data["questions"][0]["expected_answer_contains"] == ["3", "mm"]
    assert data["questions"][0]["expected_pages"] == [13]


def test_an_unanswerable_line_needs_no_document():
    data, _ = q.convert([(2, _row(answerable="false", expected_document="",
                                  expected_answer_contains=""))], "c", "a")
    assert data["questions"][0] == {"id": "R01", "question": "What is the minimum X?",
                                    "answerable": False}


@pytest.mark.parametrize("bad,match", [
    (dict(question=""), "question is empty"),
    (dict(expected_answer_contains=""), "needs expected_document"),
    (dict(answerable="maybe"), "true or false"),
    (dict(expected_pages="thirteen"), "must be numbers"),
])
def test_a_verified_line_that_cannot_be_scored_is_refused_with_its_line(bad, match):
    with pytest.raises(q.SheetError, match=f"line 7: .*{match}"):
        q.convert([(7, _row(**bad))], "c", "a")


def test_nothing_verified_is_refused_not_an_empty_set():
    with pytest.raises(q.SheetError, match="no line is marked"):
        q.convert([(2, _row(engineer_verified="no"))], "c", "a")


def test_the_output_is_what_run_eval_reads():
    sys.path.insert(0, str(REPO / "eval"))
    sys.path.insert(0, str(REPO / "backend"))
    import run_eval
    data, _ = q.convert([(2, _row())], "c", "a")
    loaded = run_eval.normalise(data)["questions"][0]
    assert loaded["expected_answer_contains"] == ["3", "mm"]
    assert loaded["expected_clauses"] == ["7.8"]


def test_the_shipped_template_has_every_column():
    rows = q.read_sheet(REPO / "gold" / "QUESTIONS-TEMPLATE.csv")
    assert rows == []
