"""Owner order 2f + 2e: internal notes leave the contractor's column; one rule
from several standards is one comment; the run says what changed in scope.

What these hold (mutations M1049-M1053):
  * the CRS sheet's COMPANY Comments column carries no internal note - no
    "requires another document", no missing standard, no unread page;
  * those notes are the "Review notes" sheet of the INTERNAL copy, grouped by
    standard with a count; the copy issued to the contractor has no such sheet;
  * a run says which standards came into or left scope since the previous run
    of the same submittal.

Synthetic data only; identifiers are made up.
"""
from __future__ import annotations

import io
import json
import uuid

from openpyxl import load_workbook

from app import db
from tests.test_crs_endpoint import (NOW, _client, _finding, _run, _submittal,  # noqa: F401
                                     temp_db)

ROD = {"ai_rationale": ("requires_other_document: this requirement names its own evidence "
                        "- a calibration certificate")}


def _world():
    doc = _submittal()
    run_id = _run(doc)
    _finding(doc, run_id, "NON_COMPLIANT")
    for _ in range(3):
        _finding(doc, run_id, "NOT_IN_DOCUMENT_SCOPE", **ROD)
    with db.connect() as conn:
        conn.execute("INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,"
                     "text,token_count,content_hash) VALUES ('c1',?,'drum.pdf',0,1,1,?,10,'h1')",
                     (doc, "Design per API 999 throughout."))
    return doc, run_id


def test_the_contractors_column_holds_no_internal_note():
    doc, run_id = _world()
    view = _client(doc).get(f"/api/reviews/runs/{run_id}/crs/preview").json()
    comments = "\n".join(r["comment"] for r in view["rows"])
    assert "API 999" not in comments and "name their own evidence" not in comments
    notes = {n["note"]: n for n in view["review_notes"]}
    assert notes["Standard not in your library - upload required"]["standard"] == "API 999"
    assert notes["Requires another document"]["count"] == 3


def test_the_issue_copy_has_no_review_notes_the_internal_copy_does():
    """M1049."""
    doc, run_id = _world()
    client = _client(doc)
    assert client.get(f"/api/reviews/runs/{run_id}/crs/preview",
                      params={"copy": "issue"}).json()["review_notes"] == []
    issued = load_workbook(io.BytesIO(client.get(f"/api/reviews/runs/{run_id}/crs",
                                                 params={"copy": "issue"}).content))
    internal = load_workbook(io.BytesIO(client.get(f"/api/reviews/runs/{run_id}/crs").content))
    assert "Review notes" not in issued.sheetnames
    assert "Review notes" in internal.sheetnames
    text = " ".join(str(c.value) for ws in issued for row in ws.iter_rows() for c in row if c.value)
    assert "name their own evidence" not in text


def _scoped_run(doc: str, created_at: str, standards: list[tuple[str, str]]) -> str:
    run_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("INSERT INTO review_runs (id,submittal_document_id,status,refusal_reason,"
                     "created_at,updated_at) VALUES (?,?,'completed',?,?,?)",
                     (run_id, doc, json.dumps({"recommended_code": None, "reason": None}),
                      created_at, created_at))
        for std_id, name in standards:
            conn.execute("INSERT OR IGNORE INTO documents (id,filename,sha256,size_bytes,"
                         "stored_path,status,page_count,uploaded_at) VALUES (?,?,?,1,'x','ready',1,?)",
                         (std_id, name, f"sha-{std_id}", NOW))
            conn.execute("INSERT INTO review_applicable_standards (id,review_run_id,"
                         "standard_document_id,selection_reason,selection_method,included,"
                         "created_at) VALUES (?,?,?,'cited','referenced',1,?)",
                         (str(uuid.uuid4()), run_id, std_id, created_at))
    return run_id


def test_a_run_says_which_standards_came_into_or_left_scope():
    """M1052: the owner saw 10 standards in scope, then 6, and no reason."""
    doc = _submittal()
    a, b, c = ("s-a", "STD-A.pdf"), ("s-b", "STD-B.pdf"), ("s-c", "STD-C.pdf")
    first = _scoped_run(doc, "2026-09-20T00:00:00Z", [a, b])
    second = _scoped_run(doc, "2026-09-21T00:00:00Z", [a, c])
    runs = {r["review_run_id"]: r for r in _client(doc, "s-a", "s-b", "s-c")
            .get("/api/reviews/runs").json()["runs"]}
    assert runs[first]["standards_change"] is None
    assert runs[second]["standards_change"] == {
        "previous_run_id": first, "added": ["STD-C.pdf"], "removed": ["STD-B.pdf"]}


def test_a_standard_the_caller_cannot_read_is_not_named_in_the_change():
    doc = _submittal()
    _scoped_run(doc, "2026-09-20T00:00:00Z", [("s-a", "STD-A.pdf")])
    second = _scoped_run(doc, "2026-09-21T00:00:00Z", [("s-secret", "SECRET.pdf")])
    [run] = [r for r in _client(doc, "s-a").get("/api/reviews/runs").json()["runs"]
             if r["review_run_id"] == second]
    assert "SECRET.pdf" not in json.dumps(run["standards_change"])
