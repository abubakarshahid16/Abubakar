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
    assert rows[0]["comment"].endswith(
        "Contractor to complete the field 'Corrosion allowance' (left blank)."
    )
    assert rows[1]["comment"].startswith(
        "Clarification requested: no field read from the datasheet was paired with Corrosion "
        "allowance; please indicate where it is stated, or confirm it is not stated.\n"
    )
    assert rows[0]["comment_key"] != rows[1]["comment_key"]
    assert rows[0]["crs_group"] != rows[1]["crs_group"], (
        "the screen keeps them apart too"
    )


def test_rows_without_a_field_label_keep_one_per_requirement():
    # No field label, but a datasheet page: still a line, one per requirement.
    unlabelled = {"matched_phrase": None, "contractor_page": 3, "fact_id": None}
    rows = _rows(
        [_question("q1", "9.1", **unlabelled), _question("q2", "9.2", **unlabelled)]
    )
    assert _partition(rows) == [["q1"], ["q2"]]
    assert all("Supporting clauses" not in r["comment"] for r in rows)


def test_a_question_with_no_datasheet_field_and_no_page_is_a_note_not_a_line():
    """#1177: a standard's question with neither a field nor a page behind it is
    the engineer's to-do (one Review note per standard), never a CRS line."""
    unplaced = {"matched_phrase": None, "contractor_page": None, "fact_id": None}
    rows = _rows(
        [_question("q1", "9.1", **unplaced), _question("q2", "9.2", **unplaced)]
    )
    assert rows == []


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
    assert lines[0] == "Clarification requested on Rated power."
    assert lines[2:] == [
        "Supporting clauses (2):",
        "- STD-100 cl. 8.1 (p.4): clause 8.1 is in kW and the value in hp.",
        "- STD-100 cl. 8.3 (p.4): clause 8.3 is in kW and the value in hp.",
    ]
    assert rows[0]["crs_action"] == "Clarification requested on Rated power."


def test_grouped_comment_lists_supporting_clauses():
    rows = _rows([_f("b", "5.1"), _f("a", "4.3"), _f("c", "10.2")])
    assert rows[0]["comment"].split("\n") == [
        "Contractor to complete the field 'Corrosion allowance' (left blank).",
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


def test_a_long_clause_is_cut_and_a_shared_clause_says_each_requirement():
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
    # order 139 part 2 (review of #1179, rule 4): every requirement is said.
    first = lines[3]
    assert first.startswith('- STD-100 cl. 4.1 (p.4): "A long word')
    assert first.endswith(' ...." "A second requirement of 4.1."')


def test_one_row_never_hides_a_second_question_of_the_same_clause():
    """Rule 4 (review of #1179): two questions on one field from ONE clause,
    with different reasons, are one row - and the row says both, because
    deciding it decides both (#986)."""
    rows = _rows(
        [
            _question("a", "5.1"),
            _question(
                "b",
                "5.1",
                reason_code="LOW_TRUST_VALUE",
                ai_rationale="LOW_TRUST_VALUE: the value was read with low trust.",
            ),
        ]
    )
    assert _partition(rows) == [["a", "b"]]
    [row] = rows
    assert row["crs_action"] == "Clarification requested on Rated power."
    assert row["comment"].split("\n")[2:] == [
        "Supporting clauses (1):",
        "- STD-100 cl. 5.1 (p.4): clause 5.1 is in kW and the value in hp."
        " the value was read with low trust.",
    ]
    # Two blank-value requirements of one clause: both sentences, too.
    [blank] = _rows(
        [
            _f("x", "6.1"),
            _f("y", "6.1", requirement_source_text="6.1 It shall be given in mm."),
        ]
    )
    assert '"It shall be given in mm."' in blank["comment"]
    assert '"The value shall be stated per clause 6.1."' in blank["comment"]


def test_single_clause_row_text_is_unchanged():
    """A field row of ONE clause prints today's sentence, byte for byte."""
    [row] = _rows([_f("a", "4.3"), _f("a2", "4.3", equipment_tag="P-102")])
    assert row["comment"] == (
        'STD-100 cl. 4.3 (p.4): "The value shall be stated per clause 4.3." '
        "Datasheet p.2, Corrosion allowance (P-101, P-102) is left blank. "
        "Contractor to complete the field 'Corrosion allowance' (left blank)."
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
    # 1b: the two parts do NOT share a number key (see the tests below).
    assert rows[0]["comment_key"] != rows[1]["comment_key"]
    assert rows[0]["crs_group"] != rows[1]["crs_group"]
    # One wording on every finding (the screen edits a whole row): one row.
    same = _rows(
        [
            _f("s1", "1.1", engineer_comment=words),
            _f("s2", "1.2", engineer_comment=words),
        ]
    )
    assert _partition(same) == [["s1", "s2"]]


def _wording(fid, clause, words, **over):
    return _f(fid, clause, engineer_comment=words, confirmed_by="eng-1", **over)


def test_rows_split_by_wording_carry_distinct_stable_keys():
    """1b: a field group whose findings carry different engineer wordings is
    several rows; they must not share one comment key (the sheet would give
    one the field's number and the others "#2", by where each happens to
    land). The row an engineer made theirs keeps the field's key; the other
    gets its own, made from its wording only."""
    field_key = crs_mapping.field_comment_key(
        crs_mapping.BUCKET_BLANK, "corrosion allowance"
    )
    words, other = "Contractor to state it per part.", "State it for the shell."
    edited = [_wording(f"w{i}", f"10.{i}", words) for i in range(3)]
    rows = _rows([*edited, _f("d", "9.9")])
    by_ids = {tuple(sorted(r["finding_ids"])): r for r in rows}
    kept = by_ids[("w0", "w1", "w2")]
    draft = by_ids[("d",)]
    assert kept["comment_key"] == field_key, "the engineer's row keeps the number key"
    assert draft["comment_key"] not in ("", field_key)
    assert draft["comment_key"] not in draft["member_keys"], "still a field row"
    # Stable: the same on every run, whatever the order of the findings or the
    # clause that leads the row, and it depends on the wording alone.
    again = _rows([_f("d", "0.1"), *reversed(edited)])
    again_draft = next(r for r in again if r["finding_ids"] == ["d"])
    assert again_draft["comment_key"] == draft["comment_key"]
    # Two edited wordings: each wording keeps its key whichever row sorts first.
    both = [
        _wording("a1", "1.1", words),
        _wording("a2", "1.2", words),
        _wording("b1", "2.1", other, contractor_page=1),
    ]
    first = {r["comment"].split("\n")[0]: r["comment_key"] for r in _rows(both)}
    moved = [{**f, "contractor_page": 9} if f["id"] == "a1" else f for f in both]
    moved = [{**f, "contractor_page": 1} if f["id"] == "b1" else f for f in moved]
    second = {r["comment"].split("\n")[0]: r["comment_key"] for r in _rows(moved)}
    assert first == second and len(set(first.values())) == 2


def test_the_field_key_stays_with_the_engineers_row_then_the_larger_one():
    """1b: which split row keeps the field's key does not depend on where the
    rows sort: the row an engineer made theirs first (even when smaller), then
    the larger, whatever the wordings' digests."""
    field_key = crs_mapping.field_comment_key(
        crs_mapping.BUCKET_BLANK, "corrosion allowance"
    )

    def holder(findings):
        [kept] = [r for r in _rows(findings) if r["comment_key"] == field_key]
        return sorted(kept["finding_ids"])

    # One confirmed edit against two drafts (no wording, not confirmed): the edit.
    assert holder(
        [
            _wording("e", "1.1", "Engineer words."),
            _f("d1", "2.1"),
            _f("d2", "2.2"),
        ]
    ) == ["e"]
    # Two confirmed wordings: the larger keeps it, whichever wording it is.
    for big, small in (("Words A.", "Words B."), ("Words B.", "Words A.")):
        assert holder(
            [
                _wording("b1", "1.1", big),
                _wording("b2", "1.2", big),
                _wording("s1", "2.1", small),
            ]
        ) == ["b1", "b2"]
    # Three wordings: three distinct keys.
    three = _rows([_wording(f"x{i}", f"{i}.1", f"Words {i}.") for i in range(3)])
    assert len({r["comment_key"] for r in three}) == 3


def test_a_row_split_off_a_non_field_group_is_not_taken_for_a_field_row():
    """1b: a breach group spanning two standards split by wording whose two
    leaders share a subject key: the second row's own key is in its
    member_keys, so `main` does not treat it as a field row replacing
    clauses."""

    def breach(fid, **over):
        return _f(
            fid,
            "7.1",
            compliance_status="NON_COMPLIANT",
            contractor_evidence_text="1 mm",
            **over,
        )

    rows = _rows(
        [
            breach("x1", engineer_comment="Words one.", confirmed_by="e"),
            breach("x2", engineer_comment="Words two.", confirmed_by="e"),
        ]
    )
    assert len(rows) == 2
    assert rows[0]["comment_key"] != rows[1]["comment_key"]
    for row in rows:
        assert row["comment_key"] in row["member_keys"]


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


def test_a_non_field_group_keeps_its_number_key_whichever_finding_leads():
    """1b: `_leader_order` now breaks a tie by clause, requirement words and
    id, so a different finding can lead a breach group that spans two
    standards. The row's permanent-number key must not depend on who leads:
    the key has no clause or standard in it, and every tied leader shares the
    requirement words, field, value and page it is made from."""

    def breach(fid, clause, doc):
        return _f(
            fid,
            clause,
            compliance_status="NON_COMPLIANT",
            contractor_evidence_text="1 mm",
            requirement_source_text="The value shall not exceed 2 mm.",
            standard_document_id=doc,
            standard_name=f"{doc}.pdf",
        )

    findings = [breach("z", "9.1", "std-9"), breach("a", "2.2", "std-2")]
    [forward] = _rows([dict(f) for f in findings])
    [backward] = _rows([dict(f) for f in reversed(findings)])
    assert forward["finding_ids"] == backward["finding_ids"] == ["a", "z"]
    assert forward["finding_id"] == backward["finding_id"] == "a"
    assert forward["comment_key"] == backward["comment_key"]
    # ... and whichever of the two leads, it is the same key.
    assert (
        crs_mapping.finding_comment_key(findings[0])
        == crs_mapping.finding_comment_key(findings[1])
        == forward["comment_key"]
    )
