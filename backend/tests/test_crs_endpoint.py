"""The CRS export route: who may export, and what the file says.

READ ACCESS SUFFICES, AND THAT IS A DECISION. Exporting writes nothing,
changes no run and records no judgement, so it asks the same question
`GET /api/reviews/findings` asks - may this caller read this submittal. A run
they may not read is 404, indistinguishable from one that is not there,
because a different answer would confirm the run exists.

A RUN WITH NO INCLUDABLE FINDINGS STILL EXPORTS. `crs_mapping` admits only
NON_COMPLIANT and NEEDS_ENGINEER_REVIEW findings; a submittal where the
machine found neither still has GAPS - standards it cites that the library
does not hold - and those are the rows that matter most on such a run. An
export that refused, or returned an empty sheet, would read as "nothing to
report" about a review that examined almost nothing.

AND NOTHING IN THE META IS INVENTED. The transmittal numbers are blank
because nobody has issued one; a CRS carrying a plausible-looking transmittal
number is a document that lies about its own provenance to whoever receives
it.

Mutations: M237-M240, `python scripts/mutation_check.py --phase 22`.
"""

from __future__ import annotations

import io
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import access, db, submittal_review
from app.config import settings
from app.main import app

NOW = "2026-09-19T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "crs.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    yield
    app.dependency_overrides.clear()
    access.set_user_resolver(None)
    db.reset_connection()


def _submittal(doc_id: str = "doc_sub", filename: str = "drum.pdf") -> str:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',4,?)",
            (doc_id, filename, f"sha-{doc_id}", filename, NOW))
    return doc_id


def _run(doc_id: str, recommended: str | None = "Manual Review Required") -> str:
    run_id = str(uuid.uuid4())
    outcome = json.dumps({
        "recommended_code": recommended,
        "reason": "the review examined 42 of approximately 385 fields",
    }) if recommended else None
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,"
            "refusal_reason,created_at,updated_at)"
            " VALUES (?,?,'completed',?,?,?)", (run_id, doc_id, outcome, NOW, NOW))
    return run_id


def _finding(doc_id: str, run_id: str, status: str, **over) -> None:
    row = {
        "id": str(uuid.uuid4()), "document_id": doc_id, "review_run_id": run_id,
        "category": "requirement_deviation", "severity": "major",
        "requirement": "r", "finding": "f", "required_action": "a",
        "compliance_status": status,
        "requirement_source_text": "The design pressure shall be 6,900 kPa.",
        "contractor_evidence_text": "2.2 bar (ga)",
        "ai_rationale": "unit_mismatch: kPa against bar (ga)",
        "standard_document_id": "doc_std", "standard_clause": "6.2.2",
        "standard_page": 14, "contractor_page": 4,
        "equipment_tag": "2003-47-V-0001A/B",
        "governing_sources": "[]", "citation_ids": "[]",
        "unresolved_evidence": "[]", "status": "open",
        "approval_status": "pending", "escalation_level": 0,
        "created_at": NOW, "updated_at": NOW,
    }
    row.update(over)
    with db.connect() as conn:
        conn.execute(
            f"INSERT INTO review_findings ({','.join(row)})"
            f" VALUES ({','.join('?' * len(row))})", list(row.values()))


def _client(*allowed: str) -> TestClient:
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="eng", allowed_document_ids=frozenset(allowed))
    return TestClient(app)


def _sheet(response):
    assert response.status_code == 200, response.text
    return load_workbook(io.BytesIO(response.content)).active


def _cells(ws, column: int) -> list:
    return [ws.cell(row=r, column=column).value
            for r in range(9, ws.max_row + 1)]


# ================================================================== scoping

def test_a_run_the_caller_cannot_read_is_not_found():
    """THE SCOPE RULE, ON THE EXPORT. 404 and not 403: a different answer
    would confirm the run exists."""
    doc = _submittal()
    run_id = _run(doc)

    response = _client().get(f"/api/reviews/runs/{run_id}/crs")

    assert response.status_code == 404


def test_a_run_that_does_not_exist_reads_exactly_the_same():
    """Indistinguishable from the refusal above, which is what makes the
    refusal safe to give."""
    doc = _submittal()
    _run(doc)

    unknown = _client(doc).get(f"/api/reviews/runs/{uuid.uuid4()}/crs")
    forbidden = _client().get(f"/api/reviews/runs/{_run(doc)}/crs")

    assert unknown.status_code == forbidden.status_code == 404
    assert unknown.json()["detail"]["code"] == forbidden.json()["detail"]["code"]


def test_read_access_is_enough_to_export():
    """Exporting is not a decision. It writes nothing and records no
    judgement, so it asks only whether the caller may read the submittal."""
    doc = _submittal()
    run_id = _run(doc)

    response = _client(doc).get(f"/api/reviews/runs/{run_id}/crs")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats")


def test_the_export_writes_nothing():
    """A GET that changed the run would be a decision wearing a download's
    clothes. Asserted on the row, not on the verb."""
    doc = _submittal()
    run_id = _run(doc)
    before = dict(db.connect().execute(
        "SELECT * FROM review_runs WHERE id = ?", (run_id,)).fetchone())

    _client(doc).get(f"/api/reviews/runs/{run_id}/crs")

    after = dict(db.connect().execute(
        "SELECT * FROM review_runs WHERE id = ?", (run_id,)).fetchone())
    assert before == after


# =============================================================== the content

def test_a_finding_becomes_a_row_with_its_citation_and_both_texts():
    """THE CITATION NAMES THE STANDARD, NOT ITS ID.

    The standard document is inserted for real here. Without it,
    `standard_name` resolves to None whether the route looks it up or not,
    and the assertion below passes against a route that never tried -
    mutation M241 reported NOT DETECTED and said so.
    """
    doc = _submittal()
    _submittal("doc_std", "SAES-D-001.pdf")
    run_id = _run(doc)
    _finding(doc, run_id, "NON_COMPLIANT")

    ws = _sheet(_client(doc, "doc_std").get(f"/api/reviews/runs/{run_id}/crs"))

    assert ws.cell(row=9, column=1).value == 1
    assert ws.cell(row=9, column=2).value == "drum.pdf"
    citation = ws.cell(row=9, column=3).value
    assert "SAES-D-001.pdf" in citation, "the citation names an id, not a standard"
    assert "doc_std" not in citation
    assert "clause 6.2.2" in citation and "p14" in citation
    assert "submittal p4" in citation
    comment = ws.cell(row=9, column=4).value
    assert "The design pressure shall be 6,900 kPa." in comment
    assert "2.2 bar (ga)" in comment
    assert "unit_mismatch" in comment


def test_the_contractor_columns_are_always_empty():
    """THEY BELONG TO THE CONTRACTOR. Pre-filling them would put words in
    their mouth in a document they are being asked to answer."""
    doc = _submittal()
    run_id = _run(doc)
    _finding(doc, run_id, "NON_COMPLIANT")
    _finding(doc, run_id, "NEEDS_ENGINEER_REVIEW")

    ws = _sheet(_client(doc).get(f"/api/reviews/runs/{run_id}/crs"))

    assert all(v in (None, "") for v in _cells(ws, 6))
    assert all(v in (None, "") for v in _cells(ws, 7))


def test_a_thousand_no_evidence_findings_do_not_become_a_thousand_rows():
    """MISSING_INFORMATION never enters individually. The drum run has 1,578
    of them; a CRS listing each would be noise, and section 13 covers the gap
    through the reference rows instead."""
    doc = _submittal()
    run_id = _run(doc)
    _finding(doc, run_id, "NON_COMPLIANT")
    for _ in range(20):
        _finding(doc, run_id, "MISSING_INFORMATION")

    ws = _sheet(_client(doc).get(f"/api/reviews/runs/{run_id}/crs"))

    items = [v for v in _cells(ws, 1) if isinstance(v, int)]
    assert items == [1], "a MISSING_INFORMATION finding reached the sheet"


def test_a_run_with_no_includable_findings_still_exports_its_gap_rows():
    """THE CASE THE SPEC NAMES. A submittal where the machine found no breach
    still has standards it cites and the library does not hold - and on such
    a run those rows are the whole report. An export that refused here would
    read as "nothing to report" about a review that examined almost nothing.
    """
    doc = _submittal()
    run_id = _run(doc)
    for _ in range(5):
        _finding(doc, run_id, "MISSING_INFORMATION")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,"
            "page_end,text,token_count,content_hash)"
            " VALUES ('c1',?,'drum.pdf',0,1,1,?,10,'h1')",
            (doc, "This vessel shall comply with 32-SAMSS-004 throughout."))

    ws = _sheet(_client(doc).get(f"/api/reviews/runs/{run_id}/crs"))

    sections = _cells(ws, 3)
    assert "References" in sections, "no gap row was written"
    gap = ws.cell(row=9, column=4).value
    assert "32-SAMSS-004" in gap
    assert "not in the standards library" in gap


def test_a_cited_standard_keeps_the_spelling_the_submittal_used():
    """MATCHED ON A NORMALISED KEY, PRINTED AS WRITTEN. The first export
    rendered "32SAMSS004", because the matching key had the punctuation
    stripped out of it - and a contractor reading that has to guess."""
    doc = _submittal()
    run_id = _run(doc)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,"
            "page_end,text,token_count,content_hash)"
            " VALUES ('c1',?,'drum.pdf',0,1,1,?,10,'h1')",
            (doc, "Per 32-SAMSS-004 and ASME B16.5 the flanges shall..."))

    ws = _sheet(_client(doc).get(f"/api/reviews/runs/{run_id}/crs"))

    text = "\n".join(str(v) for v in _cells(ws, 4))
    assert "32-SAMSS-004" in text and "32SAMSS004" not in text
    assert "ASME B16.5" in text


# =================================================================== the meta

def test_the_transmittal_numbers_are_blank_rather_than_invented():
    """A CRS carrying a plausible transmittal number lies about its own
    provenance to whoever receives it."""
    doc = _submittal()
    run_id = _run(doc)

    ws = _sheet(_client(doc).get(f"/api/reviews/runs/{run_id}/crs"))

    assert ws.cell(row=3, column=1).value == "COMPANY Transmittal No.:"
    assert ws.cell(row=3, column=3).value in (None, "")
    assert ws.cell(row=4, column=3).value in (None, "")
    assert ws.cell(row=7, column=3).value in (None, ""), "Date Responded"


def test_the_title_and_date_come_from_real_data():
    doc = _submittal(filename="216400C-2003-SP-0810-0003_00.pdf")
    run_id = _run(doc)

    ws = _sheet(_client(doc).get(f"/api/reviews/runs/{run_id}/crs"))

    assert ws.cell(row=5, column=3).value == "216400C-2003-SP-0810-0003_00.pdf"
    issued = ws.cell(row=6, column=3).value
    assert issued and len(issued) == 10 and issued[4] == "-"


def test_the_recommended_code_and_its_reason_appear_verbatim():
    doc = _submittal()
    run_id = _run(doc)
    _finding(doc, run_id, "NON_COMPLIANT")

    ws = _sheet(_client(doc).get(f"/api/reviews/runs/{run_id}/crs"))

    tail = "\n".join(
        str(ws.cell(row=r, column=c).value)
        for r in range(ws.max_row - 2, ws.max_row + 1) for c in (1, 3))
    assert "Recommended Review Code" in tail
    assert "Manual Review Required" in tail
    assert "42 of approximately 385 fields" in tail, "the reason was re-worded"


def test_the_engineers_final_code_supersedes_the_recommendation_in_the_file():
    """The CRS is what leaves the building. When an engineer has signed one,
    that is the code the contractor must see - and their reason with it."""
    doc = _submittal()
    run_id = _run(doc)
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id,email,display_name,password_hash,"
            "created_at) VALUES ('eng','e@e.test','Eng','h',?)", (NOW,))
        conn.execute(
            "UPDATE review_runs SET engineer_final_code='Approved with Comments',"
            " override_reason='both items are lookup tables', decided_by='eng'"
            " WHERE id = ?", (run_id,))

    ws = _sheet(_client(doc).get(f"/api/reviews/runs/{run_id}/crs"))

    tail = "\n".join(
        str(ws.cell(row=r, column=c).value)
        for r in range(ws.max_row - 2, ws.max_row + 1) for c in (1, 3))
    assert "Approved with Comments" in tail
    assert "both items are lookup tables" in tail


def test_the_filename_names_the_submittal_and_the_date():
    doc = _submittal(filename="216400C-2003-SP-0810-0003_00.pdf")
    run_id = _run(doc)

    response = _client(doc).get(f"/api/reviews/runs/{run_id}/crs")

    disposition = response.headers["content-disposition"]
    assert "CRS_216400C-2003-SP-0810-0003_00_" in disposition
    assert disposition.endswith('.xlsx"')


# ================================ a gap row must be TRUE, not just present
#
# THE CRS SAID SIX HELD STANDARDS WERE UNAVAILABLE. Its missing-reference
# check compared an identifier against a dict keyed by document id, so every
# cited standard became a gap row. Every test above cited a standard against
# an EMPTY library, where "missing" is always right - so none could see it.


def _standard(doc_id: str, filename: str) -> str:
    """A standard the review may be run against: COMPANY_STANDARD, current."""
    _submittal(doc_id, filename)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO document_classification (document_id,document_role,"
            "suggested_by) VALUES (?,'COMPANY_STANDARD','test')", (doc_id,))
    return doc_id


def _cites(doc_id: str, text: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,"
            "page_end,text,token_count,content_hash)"
            " VALUES (?,?,'drum.pdf',0,1,1,?,10,?)",
            (f"c-{doc_id}", doc_id, text, f"h-{doc_id}"))


def test_a_cited_standard_the_library_holds_gets_no_gap_row():
    """THE DEFECT. SAES-L-132 is held; 32-SAMSS-004 is not. Only the second
    may appear, because the first would tell a contractor a governing
    standard was missing when it was not."""
    doc = _submittal()
    held = _standard("doc_l132", "SAES-L-132.pdf")
    run_id = _run(doc)
    _cites(doc, "Design per SAES-L-132 and 32-SAMSS-004.")

    ws = _sheet(_client(doc, held).get(f"/api/reviews/runs/{run_id}/crs"))

    gaps = "\n".join(str(v) for v in _cells(ws, 4) if v)
    assert "32-SAMSS-004" in gaps
    assert "SAES-L-132" not in gaps, "a held standard was reported missing"


def test_a_held_standard_the_caller_cannot_read_is_missing_to_them():
    """SCOPED, deliberately. "Not in the library FOR THIS REVIEW" means the
    library this caller may read - a standard they hold no grant for was not
    reviewed against, and the row saying so is true."""
    doc = _submittal()
    _standard("doc_l132", "SAES-L-132.pdf")
    run_id = _run(doc)
    _cites(doc, "Design per SAES-L-132.")

    ws = _sheet(_client(doc).get(f"/api/reviews/runs/{run_id}/crs"))

    assert "SAES-L-132" in "\n".join(str(v) for v in _cells(ws, 4) if v)
