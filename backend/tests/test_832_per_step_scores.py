"""#832 (R28): each step of a review is scored on its own. Every key, standard and finding here
is INVENTED."""

from __future__ import annotations

import copy
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from tools import review_score as rs
from tools import review_steps as st

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import review_score as cli  # noqa: E402

STD = "STD-PUMP-001.pdf"
KEY = {
    "format": rs.KEY_FORMAT,
    "name": "invented-steps",
    "source": "invented",
    "document_type": "pump datasheet",
    "complete_for_flags": True,
    "standards_chosen": ["STD-PUMP-001", "STD-SEAL-002"],
    "standards_complete": True,
    "fields_read": ["design pressure", "flow", "head"],
    "fields_complete": False,
    "items": [
        {
            "id": "D1",
            "kind": "defect",
            "standard": "STD-PUMP-001",
            "clause": "4.2",
            "field": "design pressure",
        },
        {
            "id": "M1",
            "kind": "met",
            "standard": "STD-PUMP-001",
            "clause": "6.3",
            "field": "flow",
        },
        {"id": "D2", "kind": "defect", "standard": "STD-PUMP-001", "clause": "9.1"},
    ],
}


def finding(clause, status, field, std=STD):
    return {
        "id": f"f-{clause}",
        "standard": std,
        "clause": clause,
        "field": field,
        "compliance_status": status,
        "requirement_text": f"{field} shall be stated.",
    }


def run(
    findings,
    *,
    standards=("STD-PUMP-001.pdf",),
    fields=("Design pressure", "Flow rate"),
):
    return {
        "format": rs.FINDINGS_FORMAT,
        "model": "m1",
        "findings": findings,
        "standards_selected": list(standards),
        "fields_read": list(fields),
    }


def steps_of(key, doc):
    return st.step_scores(key, doc, rs.score(key, doc), rs.match_item)["steps"]


GOOD = run(
    [
        finding("4.2", "NON_COMPLIANT", "design pressure"),
        finding("6.3", "COMPLIANT", "flow"),
    ]
)


def test_reading_counts_the_fields_the_run_read_against_the_key():
    reading = steps_of(KEY, GOOD)["reading"]
    # head was not read; flow rate covers "flow"; precision is not judged (list not complete)
    assert reading["recall"] == [2, 3] and reading["missed"] == 1
    assert reading["precision"] is None and "not judged" in reading["precision_note"]


def test_standards_precision_is_judged_only_when_the_key_says_its_list_is_complete():
    standards = steps_of(KEY, GOOD)["standards"]
    assert standards["recall"] == [1, 2] and standards["extra"] == 0
    assert standards["precision"] == [1, 1]
    key = {**KEY, "standards_complete": False}
    extra = run([], standards=("STD-PUMP-001.pdf", "STD-OTHER-009.pdf"))
    standards = steps_of(key, extra)["standards"]
    assert standards["precision"] is None and standards["extra"] == 1
    judged = steps_of(KEY, extra)["standards"]
    assert judged["precision"] == [1, 2]


def test_pairing_checks_that_the_answering_finding_names_the_keys_field():
    right = steps_of(KEY, GOOD)["pairing"]
    assert right["recall"] == [2, 2] and right["paired_wrong"] == 0
    # D1 is answered, but by a finding whose own field is another field
    odd = run([finding("4.2", "NON_COMPLIANT", "design pressure")])
    odd["findings"][0]["requirement_text"] = "design pressure shall be stated."
    odd["findings"][0]["field"] = "relief setting"
    wrong = steps_of(KEY, odd)["pairing"]
    assert wrong["paired_wrong"] == 1 and wrong["no_answering_finding"] == 1
    assert wrong["recall"] == [0, 2]


def test_decision_comes_from_the_usual_score_and_wording_is_never_scored():
    steps = steps_of(KEY, GOOD)
    assert steps["decision"]["recall"] == [1, 2]
    assert steps["crs_wording"] == {"scored": False, "why": st.NOT_SCORED_WORDING}


def test_a_step_the_key_or_the_file_gives_nothing_for_is_not_scored_with_the_reason():
    bare = {
        k: v for k, v in KEY.items() if k not in ("fields_read", "standards_chosen")
    }
    steps = steps_of(bare, GOOD)
    assert steps["reading"] == {
        "scored": False,
        "why": "not scored: the key lists no fields read",
    }
    assert steps["standards"]["scored"] is False
    no_lists = {
        k: v for k, v in GOOD.items() if k not in ("fields_read", "standards_selected")
    }
    steps = steps_of(KEY, no_lists)
    assert "the findings file lists no fields read" in steps["reading"]["why"]


def test_the_table_sums_counts_per_document_type_and_never_averages_percentages():
    big = {**KEY, "name": "big", "fields_read": [f"field {i}" for i in range(8)]}
    big_run = run([], fields=[f"field {i}" for i in range(8)])
    small = {**KEY, "name": "small", "fields_read": ["field a", "field b"]}
    small_run = run([], fields=[])
    results = [
        st.step_scores(big, big_run, rs.score(big, big_run), rs.match_item),
        st.step_scores(small, small_run, rs.score(small, small_run), rs.match_item),
    ]
    text = st.table(results)
    # 8 of 8 and 0 of 2 -> 8 of 10 (80%), not the 50% an average of the two would give
    assert "8 of 10 (80%)" in text
    assert "| pump datasheet | crs_wording | not scored" in text


def test_a_key_without_a_document_type_is_a_group_of_its_own():
    key = {k: v for k, v in KEY.items() if k != "document_type"}
    result = st.step_scores(key, GOOD, rs.score(key, GOOD), rs.match_item)
    assert result["document_type"] == st.UNSTATED_TYPE


@pytest.mark.parametrize(
    "bad",
    [
        {"fields_read": "design pressure"},
        {"standards_chosen": ["ok", ""]},
        {"fields_complete": "yes"},
        {"document_type": 3},
    ],
)
def test_a_badly_shaped_optional_section_is_refused_not_skipped(bad):
    with pytest.raises(rs.KeyError_):
        rs.validate_key({**copy.deepcopy(KEY), **bad})


def test_the_key_without_the_new_sections_scores_as_before():
    old = {
        k: v
        for k, v in KEY.items()
        if k not in ("fields_read", "standards_chosen", "document_type")
    }
    assert rs.score(old, GOOD)["recall"] == 0.5


def test_export_carries_the_standards_and_fields_as_names_only():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE documents (id TEXT, filename TEXT);
        CREATE TABLE review_runs (id TEXT, submittal_document_id TEXT);
        INSERT INTO review_runs VALUES ('r1', 'sub');
        CREATE TABLE review_applicable_standards (
            review_run_id TEXT, standard_document_id TEXT, included INTEGER);
        CREATE TABLE submittal_facts (submittal_document_id TEXT, field_name TEXT, field_value TEXT, superseded_at TEXT);
        INSERT INTO documents VALUES ('s1', 'STD-PUMP-001.pdf'), ('s2', 'STD-OFF.pdf');
        INSERT INTO review_applicable_standards VALUES ('r1', 's1', 1), ('r1', 's2', 0);
        INSERT INTO submittal_facts VALUES ('sub', 'Design pressure', 'SECRET-VALUE-832', NULL),
                                           ('sub', 'Design pressure', 'again', NULL), ('sub', 'Flow', 'x', NULL),
                                           ('sub', 'Old field', 'gone', '2026-01-01');
        """
    )
    got = st.per_step_lists(conn, "r1")
    assert got == {
        "standards_selected": ["STD-PUMP-001.pdf"],
        "fields_read": ["Design pressure", "Flow"],
    }
    assert "SECRET-VALUE-832" not in json.dumps(got)


def test_the_steps_report_skips_hidden_exam_keys_and_names_keys_with_no_run(tmp_path):
    keys, runs = tmp_path / "keys", tmp_path / "runs"
    keys.mkdir()
    runs.mkdir()
    (keys / "a.json").write_text(json.dumps(KEY))
    (keys / "b.json").write_text(json.dumps({**KEY, "name": "b-no-run"}))
    (keys / "h.json").write_text(
        json.dumps({**KEY, "name": "hidden", "source": "hidden_exam"})
    )
    (runs / "invented-steps.findings.json").write_text(json.dumps(GOOD))
    text = st.report(keys, runs, "W1")
    assert "| pump datasheet | reading |" in text
    assert "b-no-run" in text and "hidden" not in text.replace("hidden-exam", "")
    assert (
        cli.main(
            [
                "steps",
                "--keys-dir",
                str(tmp_path / "hidden-exam"),
                "--runs-dir",
                str(runs),
            ]
        )
        == 2
    )


def test_a_database_without_the_tables_gives_no_list_not_an_empty_one():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    assert st.per_step_lists(conn, "r1") == {}


def test_a_standard_number_is_never_matched_by_a_longer_one_that_starts_with_it():
    assert not st._same_standard("STD-10", "STD-100.pdf")
    assert not st._same_standard("STD-100", "STD-10.pdf")
    assert not st._same_standard("API 6", "API 610")
    assert st._same_standard("STD-100", "STD-100.pdf")
    assert st._same_standard("API RP 520 Part I", "API-520-I.pdf")


def test_a_superseded_fact_is_not_a_field_read():
    # the export test above holds a superseded 'Old field': it must not be listed
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE review_runs (id TEXT, submittal_document_id TEXT);
        CREATE TABLE documents (id TEXT, filename TEXT);
        CREATE TABLE review_applicable_standards (review_run_id TEXT, standard_document_id TEXT, included INTEGER);
        CREATE TABLE submittal_facts (submittal_document_id TEXT, field_name TEXT, superseded_at TEXT);
        INSERT INTO review_runs VALUES ('r1', 'sub');
        INSERT INTO submittal_facts VALUES ('sub', 'Flow', NULL), ('sub', 'Old field', '2026-01-01');
        """
    )
    assert st.per_step_lists(conn, "r1")["fields_read"] == ["Flow"]


def test_a_precision_from_only_some_keys_says_how_many():
    complete = KEY
    open_list = {**KEY, "name": "open", "standards_complete": False}
    results = [
        st.step_scores(k, GOOD, rs.score(k, GOOD), rs.match_item)
        for k in (complete, open_list)
    ]
    text = st.table(results)
    standards_row = next(r for r in text.splitlines() if "| standards |" in r)
    assert "(1 of 2 keys)" in standards_row
    both = st.table(results[:1])
    assert "keys)" not in next(r for r in both.splitlines() if "| standards |" in r)


def test_an_unknown_run_gives_no_lists_not_empty_ones():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE review_runs (id TEXT, submittal_document_id TEXT);
        CREATE TABLE documents (id TEXT, filename TEXT);
        CREATE TABLE review_applicable_standards (review_run_id TEXT, standard_document_id TEXT, included INTEGER);
        CREATE TABLE submittal_facts (submittal_document_id TEXT, field_name TEXT, superseded_at TEXT);
        """
    )
    assert st.per_step_lists(conn, "no-such-run") == {}
