"""Order 139 part 2 (spec a, c, d): ONE COMMENT PER DATASHEET FIELD.

One blank field cited by 29 clauses was 29 CRS rows. Now a value left blank,
a value not found and an engineer's question are one row per datasheet field,
listing the clauses behind it; a breach stays one row per problem; a blank and
a not-found of the same field stay two rows (different actions); a question
with no field label keeps one row per requirement. The row's permanent-number
key is the FIELD's, so a re-run that adds a clause keeps the number, and the
row carries every finding's own key (`member_keys`) so the numbers of the old
per-clause rows can be found.

Invented findings only - no client document, no real standard text.
"""

from __future__ import annotations

import random

from app import crs_mapping
from app.crs_mapping import build_crs_rows, crs_groups

BASE = {
    "compliance_status": "MISSING_INFORMATION",
    "origin": None,
    "standard_document_id": "std-1",
    "standard_name": "STD-100.pdf",
    "standard_page": 4,
    "contractor_page": 2,
    "fact_id": "fact-1",
    "crs_field_label": "Corrosion allowance",
    "crs_is_blank": True,
    "contractor_evidence_text": "",
    "equipment_tag": "P-101",
    "approval_status": "pending",
    "ai_rationale": "",
    "severity": "minor",
}


def _f(fid: str, clause: str, **over) -> dict:
    return {
        **BASE,
        "id": fid,
        "standard_clause": clause,
        "requirement_source_text": f"{clause} The value shall be stated per clause {clause}.",
        **over,
    }


def _not_found(fid: str, clause: str, **over) -> dict:
    return _f(
        fid,
        clause,
        fact_id=None,
        contractor_page=None,
        crs_field_label=None,
        crs_is_blank=None,
        requirement_limit={"subject": "Corrosion allowance"},
        **over,
    )


def _question(fid: str, clause: str, **over) -> dict:
    return _f(
        fid,
        clause,
        **{
            "compliance_status": "NEEDS_ENGINEER_REVIEW",
            "crs_field_label": None,
            "matched_phrase": "Rated power",
            "crs_is_blank": False,
            "contractor_evidence_text": "15 hp",
            "reason_code": "unit_mismatch",
            "ai_rationale": f"unit_mismatch: clause {clause} is in kW and the value in hp.",
            **over,
        },
    )


def _rows(findings):
    return build_crs_rows(findings, [], "sheet.pdf")


def _partition(rows):
    return [sorted(r["finding_ids"]) for r in rows]


def test_one_row_per_datasheet_field():
    rows = _rows(
        [
            _f("a", "4.3"),
            _f("b", "5.1"),
            _f("c", "2.2", standard_document_id="std-2", standard_name="STD-200.pdf"),
        ]
    )
    assert _partition(rows) == [["a", "b", "c"]]
    assert rows[0]["row_kind"] == crs_mapping.ROW_KIND_MISSING_INFORMATION


def test_blank_and_not_found_stay_separate_rows():
    rows = _rows(
        [_f("blank", "3.1"), _not_found("nf1", "3.4"), _not_found("nf2", "6.2")]
    )
    assert _partition(rows) == [["blank"], ["nf1", "nf2"]]
    assert rows[0]["comment"].endswith("Contractor to provide Corrosion allowance.")
    assert rows[1]["comment"].startswith(
        "Engineer to check whether the datasheet states Corrosion allowance: no field this "
        "system read was paired with it.\n"
    )
    assert rows[0]["comment_key"] != rows[1]["comment_key"]
    assert rows[0]["crs_group"] != rows[1]["crs_group"], (
        "the screen keeps them apart too"
    )


def test_rows_without_a_field_label_keep_one_per_requirement():
    unlabelled = {"matched_phrase": None, "contractor_page": None, "fact_id": None}
    rows = _rows(
        [_question("q1", "9.1", **unlabelled), _question("q2", "9.2", **unlabelled)]
    )
    assert _partition(rows) == [["q1"], ["q2"]]
    assert all("Supporting clauses" not in r["comment"] for r in rows)


def test_breaches_stay_one_row_per_problem():
    breach = {
        "compliance_status": "NON_COMPLIANT",
        "crs_is_blank": False,
        "contractor_evidence_text": "1.5 mm",
    }
    rows = _rows([_f("n1", "7.1", **breach), _f("n2", "7.2", **breach)])
    assert _partition(rows) == [["n1"], ["n2"]]
    assert all(r["row_kind"] == crs_mapping.ROW_KIND_NON_COMPLIANT for r in rows)


def test_engineer_to_check_questions_of_one_field_are_one_row():
    rows = _rows([_question("e1", "8.1"), _question("e2", "8.3")])
    assert _partition(rows) == [["e1", "e2"]]
    lines = rows[0]["comment"].split("\n")
    assert lines[0] == "Engineer to check Rated power."
    assert lines[2:] == [
        "Supporting clauses (2):",
        "- STD-100 cl. 8.1 (p.4): clause 8.1 is in kW and the value in hp.",
        "- STD-100 cl. 8.3 (p.4): clause 8.3 is in kW and the value in hp.",
    ]
    assert rows[0]["crs_action"] == "Engineer to check Rated power."


def test_grouped_comment_lists_supporting_clauses():
    rows = _rows([_f("b", "5.1"), _f("a", "4.3"), _f("c", "10.2")])
    assert rows[0]["comment"].split("\n") == [
        "Contractor to provide Corrosion allowance.",
        "Datasheet p.2, Corrosion allowance (P-101) is left blank.",
        "Supporting clauses (3):",
        '- STD-100 cl. 4.3 (p.4): "The value shall be stated per clause 4.3."',
        '- STD-100 cl. 5.1 (p.4): "The value shall be stated per clause 5.1."',
        '- STD-100 cl. 10.2 (p.4): "The value shall be stated per clause 10.2."',
    ]
    assert rows[0]["standard_reference"].count("; ") == 2, (
        "every reference still listed"
    )


def test_long_clause_list_says_how_many_more():
    rows = _rows([_f(f"x{i}", f"3.{i}") for i in range(1, 13)])
    lines = rows[0]["comment"].split("\n")
    assert lines[2] == "Supporting clauses (12):"
    assert (
        len([line for line in lines if line.startswith("- STD-100")])
        == crs_mapping.MAX_CLAUSE_LINES
    )
    assert lines[-1] == "- and 2 more of these 12 (see Standard Reference)."
    assert rows[0]["standard_reference"].count("STD-100") == 12


def test_a_long_clause_is_cut_and_a_shared_clause_counts_its_requirements():
    long = "word " * 80
    rows = _rows(
        [
            _f("a", "4.1", requirement_source_text=f"4.1 A long {long}"),
            _f("b", "4.1", requirement_source_text="4.1 A second requirement of 4.1."),
            _f("c", "4.2"),
        ]
    )
    lines = rows[0]["comment"].split("\n")
    assert lines[2] == "Supporting clauses (2):"
    first = lines[3]
    assert first.endswith(' ...." (+1 more requirement of this clause)')
    assert len(first) < crs_mapping.CLAUSE_LINE_CHARS + 80


def test_single_clause_row_text_is_unchanged():
    """A field row of ONE clause prints today's sentence, byte for byte."""
    [row] = _rows([_f("a", "4.3"), _f("a2", "4.3", equipment_tag="P-102")])
    assert row["comment"] == (
        'STD-100 cl. 4.3 (p.4): "The value shall be stated per clause 4.3." '
        "Datasheet p.2, Corrosion allowance (P-101, P-102) is left blank. "
        "Contractor to provide Corrosion allowance."
    )
    assert row["crs_action"] is None


def test_grouped_row_names_every_finding():
    """#986: a decision on the row is a decision on every finding behind it."""
    [row] = _rows([_f(f"g{i}", f"2.{i}") for i in range(5)])
    assert sorted(row["finding_ids"]) == [f"g{i}" for i in range(5)]


def test_leader_is_the_same_whatever_the_input_order():
    findings = [_f(f"l{i}", f"{i}.1") for i in range(1, 7)]
    seen = set()
    for seed in range(6):
        shuffled = list(findings)
        random.Random(seed).shuffle(shuffled)
        [row] = _rows([dict(f) for f in shuffled])
        seen.add((row["finding_id"], row["comment"], row["comment_key"]))
    assert len(seen) == 1
    assert seen.pop()[0] == "l1"


def test_field_row_number_key_survives_a_new_clause():
    [before] = _rows([_f("a", "4.3"), _f("b", "5.1")])
    [after] = _rows([_f("z", "0.5"), _f("a", "4.3"), _f("b", "5.1")])
    assert after["finding_id"] == "z", "the new clause leads the row"
    assert after["comment_key"] == before["comment_key"]
    assert before["comment_key"] == crs_mapping.field_comment_key(
        crs_mapping.BUCKET_BLANK, "corrosion allowance"
    )


def test_different_engineer_wordings_split_same_wording_stays_one():
    words = "Contractor to state the corrosion allowance for each part."
    rows = _rows(
        [
            _f("w1", "10.1", engineer_comment=words, confirmed_by="eng-1"),
            _f("w2", "10.2", engineer_comment=words, confirmed_by="eng-1"),
            _f("w3", "10.3"),
        ]
    )
    assert _partition(rows) == [["w1", "w2"], ["w3"]]
    assert rows[0]["comment"] == words and rows[0]["engineer_confirmed"] is True
    assert rows[1]["engineer_confirmed"] is False
    # The two parts share the field's key: the sheet numbers the second "#2".
    assert rows[0]["comment_key"] == rows[1]["comment_key"]
    assert rows[0]["crs_group"] != rows[1]["crs_group"]
    # One wording on every finding (the screen edits a whole row): one row.
    same = _rows(
        [
            _f("s1", "1.1", engineer_comment=words),
            _f("s2", "1.2", engineer_comment=words),
        ]
    )
    assert _partition(same) == [["s1", "s2"]]


def test_a_field_row_carries_every_member_key():
    findings = [_f("a", "4.3"), _f("b", "5.1"), _f("c", "6.6")]
    [row] = _rows([dict(f) for f in findings])
    assert row["member_keys"] == sorted(
        crs_mapping.finding_member_key(f) for f in findings
    )
    assert row["comment_key"] not in row["member_keys"]


def test_rejected_comment_keys_include_member_keys():
    findings = [_f("a", "4.3", approval_status="rejected"), _f("b", "5.1")]
    keys = crs_mapping.rejected_comment_keys(findings)
    assert keys == {
        crs_mapping.field_comment_key(crs_mapping.BUCKET_BLANK, "corrosion allowance"),
        crs_mapping.finding_member_key(findings[0]),
    }


def test_finding_comment_key_is_the_rows_key():
    findings = [
        _f("a", "4.3"),
        _not_found("n", "3.3"),
        _f(
            "br",
            "7.1",
            compliance_status="NON_COMPLIANT",
            contractor_evidence_text="1 mm",
        ),
    ]
    rows = _rows([dict(f) for f in findings])
    by_finding = {r["finding_id"]: r["comment_key"] for r in rows}
    for f in findings:
        assert crs_mapping.finding_comment_key(f) == by_finding[f["id"]]


def test_crs_groups_is_the_grouping_build_crs_rows_prints():
    findings = [
        _f("a", "4.3"),
        _f("b", "5.1"),
        _not_found("n", "3.3"),
        _question("q", "8.1"),
        _f(
            "br",
            "7.1",
            compliance_status="NON_COMPLIANT",
            contractor_evidence_text="1 mm",
        ),
    ]
    groups = crs_groups([dict(f) for f in findings])
    rows = _rows([dict(f) for f in findings])
    assert [
        sorted(g["findings"][i]["id"] for i in range(len(g["findings"])))
        for g in groups
    ] == _partition(rows)
    assert [g["key"] for g in groups] == [r["crs_group"] for r in rows]
    assert [g["action"] for g in groups] == [r["crs_action"] for r in rows]
