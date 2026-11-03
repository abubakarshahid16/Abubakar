"""Owner 3 Nov 11:40 (a): with CRS_ONE_ROW_IGNORE_CLAUSE_ENABLED the one-row key ignores the clause and the standard but
keeps problem, field, value, verdict and page; the merged row lists every reference. Invented rows only."""

from __future__ import annotations

from app import crs_one_row as one
from app.config import settings
from tests.test_1503_one_row_per_problem import finding, row


def merged(rows, findings):
    return one.merge_rows(rows, findings, {})[0]


def clauses(monkeypatch, on=True):
    monkeypatch.setattr(settings, "crs_one_row_ignore_clause_enabled", on)


A = finding("f1", "T-1", 1, standard_clause="4.1")
B = finding("f2", "T-2", 1, standard_clause="5.3")


def test_off_a_different_clause_keeps_two_rows(monkeypatch):
    clauses(monkeypatch, False)
    rows = merged([row("f1", ref="STD-1 4.1"), row("f2", ref="STD-2 5.3")], [A, B])
    assert len(rows) == 2


def test_on_the_same_problem_value_and_page_is_one_row_listing_every_reference(
    monkeypatch,
):
    clauses(monkeypatch)
    rows = merged([row("f1", ref="STD-1 4.1"), row("f2", ref="STD-2 5.3")], [A, B])
    assert len(rows) == 1
    ref = rows[0]["standard_reference"]
    assert "STD-1 4.1" in ref and "STD-2 5.3" in ref
    assert "T-1" in rows[0]["comment"] and "T-2" in rows[0]["comment"]
    assert rows[0]["finding_ids"] == ["f1", "f2"]


def test_on_a_different_page_a_value_or_a_verdict_still_stays_apart(monkeypatch):
    clauses(monkeypatch)
    other_page = finding("f2", "T-2", 2, standard_clause="5.3")
    pair = [row("f1", ref="STD-1 4.1"), row("f2", ref="STD-2 5.3")]
    assert len(merged(pair, [A, other_page])) == 2
    other_value = finding("f2", "T-2", 1, value="13 bar", standard_clause="5.3")
    assert len(merged(pair, [A, other_value])) == 2
    other_verdict = finding(
        "f2", "T-2", 1, status="MISSING_INFORMATION", standard_clause="5.3"
    )
    assert len(merged(pair, [A, other_verdict])) == 2
