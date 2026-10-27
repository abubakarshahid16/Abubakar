"""Order 236 (owner report, M-03): the exported internal CRS must be the sheet
the screen shows - every row, and the AI wording beside the rows it belongs to.

Both the preview and the export compose through `main._crs_content`; this holds
them to the same rows and the same AI Review Comments, with AI-written items
and stored wording in the run. Invented rows only.
"""

from __future__ import annotations

from app import access, crs_wording, db, main
from tests.test_crs_endpoint import (
    NOW,
    _client,
    _finding,
    _run,
    _sheet,
    _submittal,
    temp_db,  # noqa: F401 - fixture
)


def _world():
    doc = _submittal()
    _submittal("doc_std", "SAES-D-001.pdf")
    run_id = _run(doc)
    _finding(doc, run_id, "NON_COMPLIANT")
    _finding(doc, run_id, "MISSING_INFORMATION")
    for n in range(3):
        _finding(
            doc,
            run_id,
            "NEEDS_ENGINEER_REVIEW",
            origin="ai_engineering_check",
            finding=f"Confirm the invented item {n} is fitted.",
            ai_rationale="Relates to: STD-INV-002.",
            contractor_page=1,
        )
    return doc, run_id


def test_the_export_has_every_row_the_preview_has_and_the_ai_wording(temp_db):  # noqa: F811
    doc, run_id = _world()
    scope = access.AccessScope(
        user_id="eng", allowed_document_ids=frozenset({doc, "doc_std"})
    )
    rows, *_ = main._crs_content(run_id, scope, "internal")
    machine = [r for r in rows if r["row_kind"] in crs_wording.WORDED_KINDS]
    assert machine and any(r["row_kind"] == "ai_engineering_check" for r in rows)
    crs_wording.ensure_schema()
    with db.connect() as conn:
        for r in machine:
            conn.execute(
                "INSERT INTO crs_ai_wording (review_run_id,row_key,ai_text,model,prompt_version,"
                "created_at) VALUES (?,?,?,?,?,?)",
                (
                    run_id,
                    r["crs_row_key"],
                    "Please revise: " + r["comment"],
                    "fake",
                    "v",
                    NOW,
                ),
            )
    client = _client(doc, "doc_std")
    body = client.get(f"/api/reviews/runs/{run_id}/crs/preview").json()
    ws = _sheet(client.get(f"/api/reviews/runs/{run_id}/crs"))
    assert len(body["rows"]) == len(rows)
    from tests.test_crs_endpoint import COLUMN_HEADER_ROW, _cell

    for row in body["rows"]:
        r = COLUMN_HEADER_ROW + row["item_no"]
        assert _cell(ws, r, 10) == row["ai_review_comment"]
        assert _cell(ws, r, 4) == row["comment"]
    assert any(r["ai_review_comment"].startswith("Please revise") for r in body["rows"])
    assert _cell(ws, COLUMN_HEADER_ROW + len(body["rows"]) + 1, 1) == ""


def test_the_diagnosis_counts_what_the_sheet_shows(temp_db):  # noqa: F811
    from tools import crs_row_diagnosis

    doc, run_id = _world()
    scope = access.AccessScope(
        user_id="eng", allowed_document_ids=frozenset({doc, "doc_std"})
    )
    rows, *_ = main._crs_content(run_id, scope, "internal")
    key = next(
        r["crs_row_key"] for r in rows if r["row_kind"] in crs_wording.WORDED_KINDS
    )
    crs_wording.ensure_schema()
    with db.connect() as conn:
        for k in (key, "gone-key"):
            conn.execute(
                "INSERT INTO crs_ai_wording (review_run_id,row_key,ai_text,model,prompt_version,"
                "created_at) VALUES (?,?,?,?,?,?)",
                (run_id, k, "worded", "fake", "v", NOW),
            )
    got = crs_row_diagnosis.diagnose(run_id, scope)
    assert got["rows"] == got["rows_in_view"] == len(rows)
    assert got["rows_by_kind"]["ai_engineering_check"] == 3
    assert (
        got["wording_stored"],
        got["wording_on_a_row_now"],
        got["wording_matching_no_row"],
    ) == (2, 1, 1)
    assert got["cells_with_text"] + got["cells_blank"] == got["rows"]
    assert got["cells_blank"] == 0  # order 233: a cell with no wording says why
