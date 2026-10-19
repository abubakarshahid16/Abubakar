"""Release 1a: #1178 (rank) and #1179 (one row per field) meet in one order.

The sheet's order is its rank, first (out of limit, then missing value, then
engineer to check), and the screen's `crs_order` and `crs_priority` are read
from the very rows the file is built from. So an out-of-limit datasheet check
- which the old bucket order put AFTER the blank fields - leads the sheet in
the file and on the screen alike.

MUTATION PROOF (by hand): drop the rank from `_sheet_order` (sort on the old
bucket order) and the first test fails; stop copying `priority` into the
summary rows and the second fails.

Synthetic sheet only (invented fields and clauses).
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app import access, crs_mapping, db, main
from app.main import app
from tests.test_139_crs_numbers_merge import _add_blanks
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_review_screen import world  # noqa: F401


def _add_out_of_limit_check(run) -> str:
    """A datasheet self-check (kind B) that is out of limit, on its own page."""
    conn = db.connect()
    base = dict(
        conn.execute(
            "SELECT * FROM review_findings WHERE review_run_id = ? LIMIT 1", (run,)
        ).fetchone()
    )
    row = {
        **base,
        "id": str(uuid.uuid4()),
        "origin": "datasheet_check",
        "compliance_status": "NON_COMPLIANT",
        "fact_id": None,
        "contractor_page": 9,
        "standard_clause": "",
        "requirement_id": None,
        "matched_phrase": "test pressure",
        "requirement_source_text": "Test pressure is below 1.5 times design pressure.",
        "confirmed_by": None,
        "engineer_comment": None,
        "approval_status": "pending",
    }
    conn.execute(
        f"INSERT INTO review_findings ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
        tuple(row.values()),
    )
    conn.commit()
    return row["id"]


def _file_rows(run, scope):
    rows, *_ = main._crs_content(
        run, access.AccessScope(user_id=None, allowed_document_ids=scope)
    )
    return rows


def test_an_out_of_limit_check_leads_the_file_and_the_screen_order(world):  # noqa: F811
    _sub, run, scope = world
    blanks = _add_blanks(run, ("4.1", "6.2"))
    check = _add_out_of_limit_check(run)
    rows = [r for r in _file_rows(run, scope) if r.get("finding_ids")]
    ranks = [r["priority"] for r in rows]
    assert ranks == sorted(ranks) and ranks[0] == crs_mapping.PRIORITY_OUT_OF_LIMIT
    # the check (rank 1, page 9) sits before the blank-field row (rank 2, page 1)
    position = {fid: n for n, r in enumerate(rows) for fid in r["finding_ids"]}
    assert position[check] < position[blanks[0]]
    # the screen's order is the file's order
    body = TestClient(app).get(f"/api/reviews/runs/{run}/summary").json()
    by_id = {r["finding_id"]: r for r in body["rows"]}
    assert by_id[check]["crs_order"] < by_id[blanks[0]]["crs_order"]
    assert sorted({r["crs_order"] for r in body["rows"] if "crs_order" in r}) == list(
        range(len(rows))
    )


def test_the_summary_sends_the_rank_of_the_row_the_file_prints(world):  # noqa: F811
    _sub, run, scope = world
    blanks = _add_blanks(run, ("4.1", "6.2"))
    check = _add_out_of_limit_check(run)
    rows = _file_rows(run, scope)
    file_rank = {fid: r["priority"] for r in rows for fid in r.get("finding_ids") or []}
    body = TestClient(app).get(f"/api/reviews/runs/{run}/summary").json()
    sent = {
        r["finding_id"]: r for r in body["rows"] if r.get("crs_priority") is not None
    }
    assert {fid: sent[fid]["crs_priority"] for fid in file_rank} == file_rank
    assert sent[check]["crs_priority_label"] == crs_mapping.priority_word(1)
    assert sent[blanks[0]]["crs_priority_label"] == crs_mapping.priority_word(2)
    # one rank per row: every finding of a grouped row carries that row's rank
    assert len({sent[b]["crs_priority"] for b in blanks}) == 1
