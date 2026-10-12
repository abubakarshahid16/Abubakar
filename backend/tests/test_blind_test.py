"""The blind-test scorer: an engineer's answer key against one run's CRS rows.

Pure (no database). Every rule a lenient scorer could quietly bend is held
here: a page must agree, a whole field must match, a "none" line cannot steal
a row an expected comment needs, rows that are not machine output are left
out, and a key the scorer cannot read honestly is refused with its line number.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools import blind_test

REPO = Path(__file__).resolve().parents[2]
SUB = "EF1975-DAS-M-99.pdf"


def _line(n, field, expected, page=None, tag="", clause="", submittal=SUB):
    return {"line": n, "submittal": submittal, "page": page, "field": field, "tag": tag,
            "expected": expected, "standard": "", "clause": clause, "notes": ""}


def _row(page_section, kind="non_compliant", comment="", std=""):
    return {"page_section": page_section, "row_kind": kind, "comment": comment,
            "standard_reference": std}


def test_found_missed_and_other_type_are_counted_apart():
    key = [_line(2, "Corrosion allowance", "breach", page=4),
           _line(3, "Noise level", "missing", page=3),
           _line(4, "Hydrotest pressure", "breach", page=5)]
    rows = [_row("p.4 - Corrosion allowance (V-2001)"),
            _row("p.3 - Noise level", kind="needs_engineer_review")]
    r = blind_test.score(key, rows, SUB)
    assert (r["expected_comments"], r["found"], r["found_other_type"], r["missed"]) == (3, 1, 1, 1)
    assert [o["outcome"] for o in r["lines"]] == ["found", "found, as review", "missed"]


def test_a_page_that_disagrees_is_not_a_match():
    r = blind_test.score([_line(2, "Corrosion allowance", "breach", page=4)],
                         [_row("p.3 - Corrosion allowance")], SUB)
    assert r["missed"] == 1 and r["extra_rows"] == 1


def test_a_row_with_no_page_is_not_held_to_one():
    """A value not found anywhere on the sheet has no page to agree with."""
    r = blind_test.score([_line(2, "Noise level", "missing", page=3)],
                         [_row("Noise level", kind="missing_information")], SUB)
    assert r["found"] == 1


def test_every_word_of_the_field_must_match():
    r = blind_test.score([_line(2, "Design pressure", "breach")],
                         [_row("p.2 - Design temperature")], SUB)
    assert r["missed"] == 1


def test_a_comment_where_the_engineer_said_none_is_a_false_alarm():
    key = [_line(2, "Design pressure", "none", page=2)]
    r = blind_test.score(key, [_row("p.2 - Design pressure")], SUB)
    assert (r["none_lines"], r["false_alarms"]) == (1, 1)
    assert blind_test.score(key, [], SUB)["lines"][0]["outcome"] == "correctly silent"


def test_a_none_line_cannot_steal_a_row_an_expected_comment_needs():
    key = [_line(2, "Design pressure", "none", page=2),
           _line(3, "Design pressure", "breach", page=2)]
    r = blind_test.score(key, [_row("p.2 - Design pressure")], SUB)
    assert r["found"] == 1 and r["false_alarms"] == 0


def test_rows_that_are_not_this_runs_machine_output_are_left_out():
    rows = [_row("p.1 - A", kind="engineer_comment"), _row("p.1 - B", kind="carried_forward")]
    r = blind_test.score([], rows, SUB)
    assert r["machine_rows"] == 0 and r["rows_not_machine_output"] == 2


def test_the_clause_is_checked_only_where_the_engineer_named_one():
    key = [_line(2, "Corrosion allowance", "breach", clause="7.1.2.1"),
           _line(3, "Noise level", "breach")]
    rows = [_row("p.4 - Corrosion allowance", std="SAES-A-133 cl. 7.1.2.1"),
            _row("p.3 - Noise level", std="SAES-A-105 cl. 5.3.3")]
    r = blind_test.score(key, rows, SUB)
    assert (r["clause_checked"], r["clause_agreed"]) == (1, 1)


def test_key_lines_for_another_submittal_are_skipped_and_counted():
    r = blind_test.score([_line(2, "Noise level", "breach", submittal="OTHER-DS.pdf")], [], SUB)
    assert r["key_lines_for_another_submittal"] == 1 and r["expected_comments"] == 0


def test_the_shipped_template_reads_as_an_empty_key(tmp_path):
    assert blind_test.read_key(REPO / "gold" / "FINDINGS-TEMPLATE.csv") == []


def test_a_key_that_cannot_be_scored_honestly_is_refused_with_its_line(tmp_path):
    bad = tmp_path / "k.csv"
    bad.write_text(",".join(blind_test.COLUMNS) + "\nX.pdf,4,Noise,,maybe,,,\n")
    with pytest.raises(blind_test.AnswerKeyError, match="line 2"):
        blind_test.read_key(bad)
    bad.write_text(",".join(blind_test.COLUMNS) + "\nX.pdf,four,Noise,,breach,,,\n")
    with pytest.raises(blind_test.AnswerKeyError, match="page"):
        blind_test.read_key(bad)
