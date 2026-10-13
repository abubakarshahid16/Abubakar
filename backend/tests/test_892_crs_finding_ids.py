"""#892 item 1: every CRS row names the stored finding(s) it stands on.

A grouped row is several findings (one per tag or standard). Before #892 only
the group leader's id reached `crs_mapping`, and `crs_export.build_crs_view`
dropped even that, so the preview row named no finding at all and the other
findings of a group could not be traced from the sheet. Invented runs only.
"""
from __future__ import annotations

from app import crs_export, crs_mapping
from tests.test_crs_endpoint import _client, _finding, _run, _submittal, temp_db  # noqa: F401 - fixture


def _preview(doc: str, run: str) -> list[dict]:
    r = _client(doc).get(f"/api/reviews/runs/{run}/crs/preview")
    assert r.status_code == 200, r.text
    return r.json()["rows"]


def test_a_grouped_row_names_every_finding_it_stands_on():
    doc = _submittal()
    run = _run(doc)
    # One problem on two tags: one row, two findings.
    _finding(doc, run, "NON_COMPLIANT", id="f-a", equipment_tag="T-1")
    _finding(doc, run, "NON_COMPLIANT", id="f-b", equipment_tag="T-2")
    rows = [r for r in _preview(doc, run) if r["row_kind"] == "non_compliant"]
    assert len(rows) == 1
    assert sorted(rows[0]["finding_ids"]) == ["f-a", "f-b"]


def test_a_row_no_finding_stands_on_names_none():
    rows = crs_mapping.standards_check_rows(
        {"required_not_cited": [{"identifier": "STD-1", "reason": "x"}]}, "s.pdf")
    view = crs_export.build_crs_view(rows, {"review_run_id": "run-1"})
    assert view["rows"][0]["finding_ids"] == []


def test_a_caller_sending_only_the_single_id_still_gets_it_listed():
    view = crs_export.build_crs_view(
        [{"finding_id": "f-1", "document_name": "s.pdf", "page_section": "", "comment": "c",
          "comment_by": "AI Review"}], {"review_run_id": "run-1"})
    assert view["rows"][0]["finding_ids"] == ["f-1"]


def test_the_ids_are_each_listed_once_in_the_rows_order():
    assert crs_mapping.finding_ids([{"id": "b"}, {"id": "a"}, {"id": "b"}, {}]) == ["b", "a"]
