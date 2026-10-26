"""K7/K8 (code audit 26 Oct, order 224): real rows, run through the issue gate's own scan.

The five things the planner's review named, each shown on a row built from findings: the
reference of a table-number clause, the one-clause heading, a bare blank marker, "this
engine" in a comment, and a question row's reason. Every row the program words by itself
must pass `scan_issue_rows` as the engineer's tick; a row that still carries the
program's voice is the one the gate stops. Invented findings only.
"""

from __future__ import annotations

from app import crs_machine_words as mw
from app import crs_mapping
from tests.test_139_crs_one_per_field import _f, _not_found, _question


def _ticked(rows):
    return [{**r, "engineer_confirmed": True} for r in rows]


def _build(findings):
    return crs_mapping.build_crs_rows(findings, [], "sheet.pdf")


def test_a_table_number_clause_prints_no_paragraph_not_identified():
    row = _build(
        [
            _f(
                "t1",
                "0.3",
                compliance_status="NON_COMPLIANT",
                crs_is_blank=False,
                contractor_evidence_text="1.5 mm",
                clause_identified=False,
            )
        ]
    )[0]
    assert "paragraph not identified" not in row["standard_reference"]
    assert (
        "0.3" not in row["standard_reference"] and "(p.4)" in row["standard_reference"]
    )
    assert mw.scan_issue_rows(_ticked([row])) == []


def test_a_field_row_with_one_clause_and_two_asks_has_a_singular_heading():
    [row] = _build(
        [
            _question("a", "5.1"),
            _question("b", "5.1", ai_rationale="unit_mismatch: another reason."),
        ]
    )
    assert "Supporting clause (1):" in row["comment"]
    assert "Supporting clauses (1):" not in row["comment"]


def test_a_bare_blank_marker_is_not_printed_back_to_the_contractor():
    [row] = _build([_f("b1", "4.1", contractor_evidence_text="___")])
    assert "'___'" not in row["comment"] and "is left blank" in row["comment"]
    [row] = _build([_f("b2", "4.1", contractor_evidence_text="TBA")])
    assert "'TBA'" in row["comment"]  # a real word the sheet wrote is still quoted


def test_a_question_row_is_worded_for_the_contractor_and_passes_the_gate_as_ticked():
    [row] = _build(
        [
            _question(
                "q1",
                "8.1",
                crs_field_label="Rated power",
                ai_rationale="LOW_TRUST_VALUE: the value was read with validation state x.",
            )
        ]
    )
    assert "Clarification requested: please confirm" in row["comment"]
    assert "validation state" not in row["comment"]
    assert (
        "validation state" in row["reasoning"]
    )  # the engineer reads why, in the internal cell
    assert mw.scan_issue_rows(_ticked([row])) == []


def test_a_not_found_row_passes_the_gate_as_ticked():
    [row] = _build([_not_found("n1", "3.4")])
    assert mw.scan_issue_rows(_ticked([row])) == []


def test_a_ticked_row_that_still_says_this_engine_is_stopped():
    [row] = _build([_not_found("n2", "3.5")])
    stuck = {
        **row,
        "comment": "The requirement states no limit this engine reads.",
        "engineer_confirmed": True,
    }
    [hit] = mw.scan_issue_rows([stuck])
    assert hit["cell"] == "comment" and hit["words"] == ["this engine reads"]
