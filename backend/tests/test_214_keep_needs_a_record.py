"""Order 214 fix 10: a kept comment has a named reason on the record.

Keep, Keep all remaining and an edit go through the same decision route as a
removal. A comment kept the old way (a confirmation with no decision record)
stays an open item at the issue gate until it is kept again, so no kept row is
without a named reason. Nothing is back-filled, and a record never changes a
finding's verdict. Invented runs and findings only.
"""

from __future__ import annotations

import uuid

import pytest

from app import crs_issue, review
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    NOW,
    _finding,
    _run,
    _submittal,
    temp_db,
)


def _kept_old_way() -> tuple[str, str]:
    doc = _submittal()
    run = _run(doc)
    fid = str(uuid.uuid4())
    _finding(doc, run, "NON_COMPLIANT", id=fid, confirmed_by="eng", confirmed_at=NOW)
    return run, fid


def _row(fid: str, **over) -> dict:
    return {
        "finding_id": fid,
        "crs_row_key": f"k-{fid}",
        "engineer_confirmed": True,
        "row_kind": "deviation",
        **over,
    }


def _open(run: str, rows: list[dict]) -> dict:
    return crs_issue.open_items(run, rows, {"pages_total": 1, "pages_read": [1]})


def test_a_comment_kept_the_old_way_stays_open():
    run, fid = _kept_old_way()
    gate = _open(run, [_row(fid)])
    assert [f["finding_id"] for f in gate["open_findings"]] == [fid]
    assert not gate["issuable"]


def test_keeping_it_again_with_a_named_reason_closes_it():
    run, fid = _kept_old_way()
    rec = crs_issue.decide_finding(
        run, fid, "accept", reason="", actor="eng", reason_code="kept_as_written"
    )
    assert (
        rec["reason"] == "Kept as written" and rec["reason_code"] == "kept_as_written"
    )
    assert _open(run, [_row(fid)])["open_findings"] == []


def test_a_bulk_click_writes_one_record_per_row_sharing_a_click_id():
    run, _ = _kept_old_way()
    ids = [str(uuid.uuid4()) for _ in range(3)]
    for fid in ids:
        crs_issue.decide_finding(
            run,
            fid,
            "accept",
            reason="",
            actor="eng",
            reason_code="kept_in_bulk",
            click_id="click-1",
        )
    got = [d for d in crs_issue.decisions(run) if d["click_id"] == "click-1"]
    assert sorted(d["subject"] for d in got) == sorted(ids)
    assert {d["reason_code"] for d in got} == {"kept_in_bulk"}


def test_the_reason_must_be_on_the_list_for_its_decision():
    run, fid = _kept_old_way()
    with pytest.raises(crs_issue.IssueError):
        crs_issue.decide_finding(
            run, fid, "accept", reason="", actor="eng", reason_code="duplicate"
        )  # a removal reason
    with pytest.raises(crs_issue.IssueError):
        crs_issue.decide_finding(
            run, fid, "reject", reason="", actor="eng", reason_code="kept_as_written"
        )
    with pytest.raises(crs_issue.IssueError):
        crs_issue.decide_finding(
            run, fid, "accept", reason="", actor="eng", reason_code="anything I type"
        )


def test_a_keep_without_a_code_still_needs_typed_words():
    run, fid = _kept_old_way()
    with pytest.raises(crs_issue.IssueError):
        crs_issue.decide_finding(run, fid, "accept", reason="ok", actor="eng")


def test_chat_comments_carried_numbers_and_rows_without_a_finding_are_not_held():
    doc = _submittal()
    run = _run(doc)
    chat = str(uuid.uuid4())
    _finding(doc, run, "NON_COMPLIANT", id=chat, origin="chat", confirmed_by="eng")
    other = str(uuid.uuid4())
    _finding(doc, run, "NON_COMPLIANT", id=other, confirmed_by="eng")
    rows = [_row(chat), _row(other, crs_ref="CRS-0001"), _row("", crs_row_key="k-none")]
    assert _open(run, rows)["open_findings"] == []


def test_a_record_never_changes_the_verdict_of_a_failed_requirement():
    run, fid = _kept_old_way()
    before = review.get(fid)["compliance_status"]
    crs_issue.decide_finding(
        run, fid, "accept", reason="", actor="eng", reason_code="kept_as_written"
    )
    assert review.get(fid)["compliance_status"] == before == "NON_COMPLIANT"
