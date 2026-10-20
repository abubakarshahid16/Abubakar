"""Order 161 item D: CRS row hygiene.

A CRS shows ONE row per field. Items of one field that differ only in an item
index (a nozzle mark, a pass number) and share a page, an outcome and the
whole set of clauses are ONE row listing the items; items that differ in the
clauses behind them, or whose marks are not one series, stay apart.

Invented findings only - no client document, no real standard text.
"""

from __future__ import annotations

import random

from app import crs_mapping
from app.crs_mapping import build_crs_rows, crs_groups

BASE = {
    "compliance_status": "NEEDS_ENGINEER_REVIEW",
    "origin": None,
    "standard_document_id": "std-1",
    "standard_name": "STD-100.pdf",
    "standard_page": 4,
    "standard_clause": "4.2",
    "requirement_source_text": "4.2 The size shall be as specified.",
    "contractor_page": 6,
    "fact_id": "fact-1",
    "crs_is_blank": False,
    "equipment_tag": "V-100",
    "approval_status": "pending",
    "reason_code": "no_numeric_limit",
    "ai_rationale": "no_numeric_limit: the requirement states no numeric limit.",
    "severity": "minor",
}


def _item(fid: str, label: str, value: str, clause: str = "4.2", **over) -> dict:
    return {
        **BASE,
        "id": fid,
        "fact_id": f"fact-{fid}",
        "crs_field_label": label,
        "contractor_evidence_text": value,
        "standard_clause": clause,
        "requirement_source_text": f"{clause} The size shall be as specified.",
        **over,
    }


def _series(label_of, values, clauses=("4.2",)) -> list[dict]:
    out = []
    for i, value in enumerate(values, start=1):
        for clause in clauses:
            out.append(_item(f"{i}-{clause}", label_of(i), value, clause))
    return out


def _rows(findings):
    return build_crs_rows(findings, [], "sheet.pdf")


def _field_rows(rows):
    return [r for r in rows if r["row_kind"] == "needs_engineer_review"]


def test_repeated_items_with_one_rule_and_outcome_make_one_row():
    findings = _series(lambda i: f"N{i} Size", ["4", "2", "4", "2", "3", "2", "2", "2"])
    rows = _field_rows(_rows(findings))
    assert len(rows) == 1
    row = rows[0]
    assert sorted(row["finding_ids"]) == sorted(f["id"] for f in findings)
    # the row names its items and each item's own value, never the first one's
    text = row["comment"]
    for mark in ("N1", "N2", "N8"):
        assert mark in text or mark in row["page_section"]
    assert "N1 states 4" in text and "N2 states 2" in text and "N5 states 3" in text
    assert text.index("N1 states") < text.index("N2 states") < text.index("N8 states")
    assert row["page_section"].startswith("p.6 - Size")


def test_the_screen_groups_the_items_exactly_as_the_file_does():
    findings = _series(lambda i: f"N{i} Size", ["4", "2", "3"])
    groups = [
        g for g in crs_groups(findings) if g["bucket"] == crs_mapping.BUCKET_QUESTION
    ]
    assert len(groups) == 1
    assert len(groups[0]["findings"]) == 3
    assert len({g["key"] for g in crs_groups(findings)}) == 1


def test_items_that_share_a_value_still_name_every_item():
    rows = _field_rows(_rows(_series(lambda i: f"N{i} Size", ["2", "2", "2"])))
    assert len(rows) == 1
    assert "N1" in rows[0]["page_section"] and "N3" in rows[0]["page_section"]


def test_the_number_key_does_not_depend_on_which_item_leads():
    findings = _series(lambda i: f"N{i} Size", ["4", "2", "3"])
    keys = set()
    for seed in range(6):
        shuffled = [dict(f) for f in findings]
        random.Random(seed).shuffle(shuffled)
        keys.add(_field_rows(_rows(shuffled))[0]["comment_key"])
    assert len(keys) == 1


def test_items_behind_different_clauses_stay_separate_rows():
    findings = _series(lambda i: f"N{i} Size", ["4", "2"])
    findings.append(_item("3-x", "N3 Size", "3", "9.9"))
    rows = _field_rows(_rows(findings))
    assert len(rows) == 3


def test_items_on_different_pages_stay_separate_rows():
    findings = [
        _item("a", "N1 Size", "4"),
        _item("b", "N2 Size", "2", contractor_page=7),
    ]
    assert len(_field_rows(_rows(findings))) == 2


def test_labels_that_are_not_one_series_are_never_merged():
    # H2 and O2 are two different quantities, not two items of one series
    findings = [_item("a", "H2 content", "1"), _item("b", "O2 content", "2")]
    assert len(_field_rows(_rows(findings))) == 2


def test_one_item_alone_keeps_its_own_label():
    rows = _field_rows(_rows([_item("a", "N1 Size", "4")]))
    assert len(rows) == 1
    assert "N1 Size" in rows[0]["page_section"]


def test_grouping_twice_gives_the_same_rows():
    findings = _series(lambda i: f"N{i} Size", ["4", "2", "3"])
    first = _rows(findings)
    second = _rows(findings)
    assert [r["comment"] for r in first] == [r["comment"] for r in second]
    assert [r["comment_key"] for r in first] == [r["comment_key"] for r in second]


def test_a_rejected_item_does_not_make_a_series():
    findings = [
        _item("a", "N1 Size", "4"),
        _item("b", "N2 Size", "2", approval_status="rejected"),
    ]
    rows = _field_rows(_rows(findings))
    assert len(rows) == 1
    assert "N1 Size" in rows[0]["page_section"]


def test_a_series_on_two_tags_says_which_tag_has_which_value():
    findings = []
    for tag, values in (("V-100", ["4", "2"]), ("V-200", ["9", "9"])):
        for i, value in enumerate(values, start=1):
            findings.append(_item(f"{tag}-{i}", f"N{i} Size", value, equipment_tag=tag))
    rows = _field_rows(_rows(findings))
    assert len(rows) == 1
    text = rows[0]["comment"]
    assert "V-100 N1 states 4" in text
    assert "V-200 N1 states 9" in text
    assert "V-200 N2 states 9" in text


def test_an_engineers_confirmed_comment_is_never_relabelled_or_merged():
    findings = _series(lambda i: f"N{i} Size", ["4", "2", "3"])
    findings[0]["confirmed_by"] = "eng-1"
    findings[0]["engineer_comment"] = "Contractor to confirm the N1 size."
    rows = _field_rows(_rows(findings))
    assert len(rows) == 2
    confirmed = [r for r in rows if r["engineer_confirmed"]]
    assert len(confirmed) == 1
    assert "N1 Size" in confirmed[0]["page_section"]
    assert (
        "items N2, N3"
        in next(r for r in rows if not r["engineer_confirmed"])["page_section"]
    )


def test_ratings_and_sizes_are_not_items_of_a_series():
    findings = [
        _item("a", "Class 150 Flange", "x"),
        _item("b", "Class 300 Flange", "y"),
    ]
    rows = _field_rows(_rows(findings))
    assert len(rows) == 2
    assert all("items" not in r["page_section"] for r in rows)


def test_the_merged_row_keeps_the_per_item_number_keys_earlier_runs_stored():
    findings = _series(lambda i: f"N{i} Size", ["4", "2"])
    before = {crs_mapping.finding_member_key(dict(f)) for f in findings}
    row = _field_rows(_rows(findings))[0]
    assert before <= set(row["member_keys"])


def test_a_number_issued_on_an_items_own_row_is_found_from_the_series_row():
    findings = _series(lambda i: f"N{i} Size", ["4", "2"])
    own_rows = [
        crs_mapping.field_comment_key(crs_mapping.BUCKET_QUESTION, f"N{i} Size")
        for i in (1, 2)
    ]
    row = _field_rows(_rows(findings))[0]
    assert set(own_rows) <= set(row["member_keys"])
    assert row["comment_key"] not in own_rows
