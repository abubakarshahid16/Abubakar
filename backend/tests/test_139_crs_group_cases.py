"""Order 139 part 2, spec b: the shared case table, backend side.

`contracts/fixtures/crs_group_cases.json` is the ONE list of grouping and order
cases both the server and the screen must pass (the screen's half is
`crs/crsGroups.parity.test.ts`). Every case runs through `crs_groups` AND
`build_crs_rows`: the groups are the expected rows (finding ids as a set, in
order; the action line; the clause count), and the rows the file prints stand
on exactly the same findings in the same order. The rank fields of the table
(`priority`, `priority_label`) are order 139's other half (section f) and are
checked by its own tests.

Invented data only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import crs_mapping
from app.api import run_summary

CASES = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "fixtures"
        / "crs_group_cases.json"
    ).read_text(encoding="utf-8")
)


def _findings(case: dict) -> list[dict]:
    return [{**CASES["base_finding"], **f} for f in case["findings"]]


@pytest.mark.parametrize(
    "case", CASES["cases"], ids=[c["name"] for c in CASES["cases"]]
)
def test_crs_groups_gives_the_expected_rows(case):
    groups = crs_mapping.crs_groups(_findings(case))
    assert [{f["id"] for f in g["findings"]} for g in groups] == [
        set(r["finding_ids"]) for r in case["expected_rows"]
    ]
    assert [g["action"] for g in groups] == [r["action"] for r in case["expected_rows"]]
    assert [crs_mapping.clause_count(g["findings"]) for g in groups] == [
        r["clause_count"] for r in case["expected_rows"]
    ]
    on_rows = {f["id"] for g in groups for f in g["findings"]}
    assert not on_rows & set(case["not_on_sheet"])


@pytest.mark.parametrize(
    "case", CASES["cases"], ids=[c["name"] for c in CASES["cases"]]
)
def test_the_file_prints_the_same_rows_in_the_same_order(case):
    groups = crs_mapping.crs_groups(_findings(case))
    rows = crs_mapping.build_crs_rows(_findings(case), [], "sheet.pdf")
    assert [set(r.get("finding_ids") or [r["finding_id"]]) for r in rows] == [
        {f["id"] for f in g["findings"]} for g in groups
    ]
    assert [r["crs_group"] for r in rows] == [g["key"] for g in groups]
    assert [r.get("crs_action") for r in rows] == [g["action"] for g in groups]


@pytest.mark.parametrize(
    "case", CASES["cases"], ids=[c["name"] for c in CASES["cases"]]
)
def test_the_summary_marks_exactly_the_review_notes(case):
    """Covers #1177's screen gap: a finding the file lists in its Review notes
    instead of on a row is sent as `crs_note`, read from the rows the file
    actually built - and no other finding is."""
    findings = _findings(case)
    fields = run_summary.crs_row_fields(
        crs_mapping.build_crs_rows(findings, [], "sheet.pdf"), findings
    )
    assert {i for i, v in fields.items() if v.get("crs_note")} == set(
        case.get("review_notes", [])
    )


def test_the_table_covers_every_field_grouped_bucket_and_a_split():
    """The table must keep exercising what it is for (a vacuous table would
    pass anything): a merged blank row, a merged not-found row, a merged
    question row, an engineer-wording split and a row that is not a row."""
    seen = set()
    for case in CASES["cases"]:
        for g in crs_mapping.crs_groups(_findings(case)):
            if len(g["findings"]) > 1:
                seen.add(g["bucket"])
            if ":e" in g["key"]:
                seen.add("split")
    assert {
        crs_mapping.BUCKET_BLANK,
        crs_mapping.BUCKET_NOT_FOUND,
        crs_mapping.BUCKET_QUESTION,
        "split",
    } <= seen
    assert any(case["not_on_sheet"] for case in CASES["cases"])
