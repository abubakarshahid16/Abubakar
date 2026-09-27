"""The CRS export route: who may export, and what the file says.

READ ACCESS SUFFICES, AND THAT IS A DECISION. Exporting writes nothing,
changes no run and records no judgement, so it asks the same question
`GET /api/reviews/findings` asks - may this caller read this submittal. A run
they may not read is 404, indistinguishable from one that is not there,
because a different answer would confirm the run exists.

A RUN WITH NO INCLUDABLE FINDINGS STILL EXPORTS. `crs_mapping` gives only
NON_COMPLIANT and NEEDS_ENGINEER_REVIEW findings a row each; a submittal
where the machine found neither still has GAPS - standards it cites that the
library does not hold - and those are the rows that matter most on such a
run. An export that refused, or returned an empty sheet, would read as
"nothing to report" about a review that examined almost nothing. Issue #165:
MISSING_INFORMATION and requires-another-document findings still never enter
individually (real runs carry hundreds of each), but each bucket now earns
one summary row stating its own count rather than vanishing entirely.

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
from app.crs_export import (COLUMN_HEADER_ROW, FIRST_DATA_ROW,
                            HEADER_FIELDS, HEADERS)
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


def _notes(response) -> str:
    """Owner order 2f: the "Review notes" sheet, as one text - where a cited
    standard not held is now recorded (never in COMPANY Comments)."""
    assert response.status_code == 200, response.text
    book = load_workbook(io.BytesIO(response.content))
    return "\n".join(str(c.value) for row in book["Review notes"].iter_rows() for c in row
                     if c.value is not None)


def _cells(ws, column: int) -> list:
    # FIRST_DATA_ROW, never a literal 9: the table moves down the sheet every
    # time a header field is added, and a hardcoded row would quietly read
    # the column headers instead of the data and still pass.
    return [ws.cell(row=r, column=column).value
            for r in range(FIRST_DATA_ROW, ws.max_row + 1)]


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

    assert ws.cell(row=FIRST_DATA_ROW, column=1).value == 1
    assert ws.cell(row=FIRST_DATA_ROW, column=2).value == "drum.pdf"
    # CRS quick wins: the standard and clause in their OWN column (8) ...
    citation = ws.cell(row=FIRST_DATA_ROW, column=8).value
    assert "SAES-D-001" in citation, "the citation names an id, not a standard"
    assert "doc_std" not in citation and ".pdf" not in citation
    assert "cl. 6.2.2" in citation and "p.14" in citation
    # ... and Page/Section is the SUBMITTAL's page, never the standard's file.
    assert ws.cell(row=FIRST_DATA_ROW, column=3).value.startswith("p.4")
    comment = ws.cell(row=FIRST_DATA_ROW, column=4).value
    assert "The design pressure shall be 6,900 kPa" in comment
    assert "2.2 bar (ga)" in comment
    assert "Contractor to revise" in comment


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


def test_every_missing_value_is_its_own_row_and_duplicates_are_one():
    """CRS QUICK WINS (supersedes #165's summary row): one row per missing
    field - the summary row hid a vibration breach, a hydrotest shortfall and
    a nozzle breach on the audit's planted sheets. Twenty findings about THE
    SAME field and value (the same clause, the same printed value, the same
    page) are still one row, not twenty."""
    doc = _submittal()
    run_id = _run(doc)
    _finding(doc, run_id, "NON_COMPLIANT")
    for _ in range(20):
        _finding(doc, run_id, "MISSING_INFORMATION", contractor_evidence_text="*")
    for n in range(3):
        _finding(doc, run_id, "MISSING_INFORMATION", contractor_evidence_text="*",
                 requirement_source_text=f"Field {n} shall be stated.")

    ws = _sheet(_client(doc).get(f"/api/reviews/runs/{run_id}/crs"))

    items = [v for v in _cells(ws, 1) if isinstance(v, int)]
    assert items == [1, 2, 3, 4, 5], items
    comments = [str(v) for v in _cells(ws, 4) if v]
    assert not any("not itemized" in c for c in comments)
    assert sum("Field " in c for c in comments) == 3


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
            (doc, "This vessel shall comply with API 998 throughout."))

    response = _client(doc).get(f"/api/reviews/runs/{run_id}/crs")
    ws = _sheet(response)

    # 2f: the gap is an internal Review note, not a comment to the contractor.
    notes = _notes(response)
    assert "API 998" in notes, "no gap note was written"
    assert "Standard not in your library - upload required" in notes
    assert "API 998" not in "\n".join(str(v) for v in _cells(ws, 4) if v)


def test_a_cited_standard_keeps_the_spelling_the_submittal_used():
    """MATCHED ON A NORMALISED KEY, PRINTED AS WRITTEN. The first export
    rendered "API998", because the matching key had the punctuation
    stripped out of it - and a contractor reading that has to guess."""
    doc = _submittal()
    run_id = _run(doc)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,"
            "page_end,text,token_count,content_hash)"
            " VALUES ('c1',?,'drum.pdf',0,1,1,?,10,'h1')",
            (doc, "Per API 998 and ASME B16.5 the flanges shall..."))

    text = _notes(_client(doc).get(f"/api/reviews/runs/{run_id}/crs"))
    assert "API 998" in text and "API998" not in text
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
    assert ws.cell(row=2 + len(HEADER_FIELDS), column=3).value in (
        None, ""), "Date Responded"


def test_the_title_and_date_come_from_real_data():
    doc = _submittal(filename="P-1000001-2003-SP-0810-0003_00.pdf")
    run_id = _run(doc)

    ws = _sheet(_client(doc).get(f"/api/reviews/runs/{run_id}/crs"))

    title_row = 3 + [k for _, k in HEADER_FIELDS].index("document_title")
    assert ws.cell(row=title_row, column=3).value == (
        "P-1000001-2003-SP-0810-0003_00.pdf")
    issued = ws.cell(row=title_row + 1, column=3).value
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
    doc = _submittal(filename="P-1000001-2003-SP-0810-0003_00.pdf")
    run_id = _run(doc)

    response = _client(doc).get(f"/api/reviews/runs/{run_id}/crs")

    disposition = response.headers["content-disposition"]
    assert "CRS_P-1000001-2003-SP-0810-0003_00_" in disposition
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
    """THE DEFECT. API 997 is held; API 998 is not. Only the second
    may appear, because the first would tell a contractor a governing
    standard was missing when it was not."""
    doc = _submittal()
    held = _standard("doc_l132", "API 997.pdf")
    run_id = _run(doc)
    _cites(doc, "Design per API 997 and API 998.")

    gaps = _notes(_client(doc, held).get(f"/api/reviews/runs/{run_id}/crs"))
    assert "API 998" in gaps
    assert "API 997" not in gaps, "a held standard was reported missing"


def test_a_held_standard_the_caller_cannot_read_is_missing_to_them():
    """SCOPED, deliberately. "Not in the library FOR THIS REVIEW" means the
    library this caller may read - a standard they hold no grant for was not
    reviewed against, and the row saying so is true."""
    doc = _submittal()
    _standard("doc_l132", "API 997.pdf")
    run_id = _run(doc)
    _cites(doc, "Design per API 997.")

    assert "API 997" in _notes(_client(doc).get(f"/api/reviews/runs/{run_id}/crs"))


# ============================================== the in-app preview of the CRS
#
# WHY THE PREVIEW EXISTS. The only way to see the deliverable was to download
# it and open Excel - in a client demo, leaving the application to show the
# thing the application produces.
#
# WHY THESE TESTS EXIST. A preview is only worth having if it says what the
# file says. `test_the_preview_is_the_workbook_row_for_row` is the point of
# the whole feature: it reads both renderings of the SAME run and compares
# them cell by cell, so a change that taught one path something the other
# does not know fails here rather than in front of a contractor.


def _preview(response):
    assert response.status_code == 200, response.text
    return response.json()


def _cell(ws, row: int, column: int):
    """A workbook cell as the preview spells it: an empty cell is "", not None.

    openpyxl reads a blank cell as None and JSON carries "". The difference is
    the encoding, not the content, so it is normalised here rather than
    papered over with a looser assertion in each test.
    """
    value = ws.cell(row=row, column=column).value
    return "" if value is None else value


def test_a_run_the_caller_cannot_read_has_no_preview_either():
    """THE SAME SCOPE AS THE EXPORT. A second route onto the same content is a
    second way in if it asks an easier question; this one asks the same."""
    doc = _submittal()
    run_id = _run(doc)
    _finding(doc, run_id, "NON_COMPLIANT")

    response = _client().get(f"/api/reviews/runs/{run_id}/crs/preview")

    assert response.status_code == 404


def test_a_preview_of_a_run_that_does_not_exist_reads_exactly_the_same():
    """Indistinguishable from the refusal above - otherwise the preview route
    confirms the existence of runs the export route refuses to."""
    doc = _submittal()

    unknown = _client(doc).get(f"/api/reviews/runs/{uuid.uuid4()}/crs/preview")
    forbidden = _client().get(f"/api/reviews/runs/{_run(doc)}/crs/preview")

    assert unknown.status_code == forbidden.status_code == 404
    assert unknown.json()["detail"]["code"] == forbidden.json()["detail"]["code"]


def test_read_access_is_enough_to_preview():
    """Previewing decides nothing and records nothing, so it asks only
    whether the caller may read the submittal - exactly as exporting does."""
    doc = _submittal()
    run_id = _run(doc)

    response = _client(doc).get(f"/api/reviews/runs/{run_id}/crs/preview")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")


def test_the_preview_writes_nothing():
    """A GET that changed the run would be a decision wearing a viewer's
    clothes. Asserted on the row, not on the verb."""
    doc = _submittal()
    run_id = _run(doc)
    _finding(doc, run_id, "NON_COMPLIANT")
    before = dict(db.connect().execute(
        "SELECT * FROM review_runs WHERE id = ?", (run_id,)).fetchone())

    _client(doc).get(f"/api/reviews/runs/{run_id}/crs/preview")

    after = dict(db.connect().execute(
        "SELECT * FROM review_runs WHERE id = ?", (run_id,)).fetchone())
    assert before == after


def test_the_preview_carries_the_seven_columns_the_template_defines():
    doc = _submittal()
    run_id = _run(doc)

    body = _preview(_client(doc).get(f"/api/reviews/runs/{run_id}/crs/preview"))

    # The template's seven, in order; the internal review copy (the default)
    # adds "AI Review Comments" LAST (owner decision 2026-09-27), and the
    # copy issued to the contractor is the template exactly.
    # CRS quick wins: "Standard Reference" follows the seven, in both copies.
    assert body["columns"] == [*HEADERS, "Standard Reference", "AI Review Comments"]
    assert body["columns"][5:7] == ["Contractor's Response", "Final Resolution"]
    issued = _preview(_client(doc).get(f"/api/reviews/runs/{run_id}/crs/preview",
                                       params={"copy": "issue"}))
    assert issued["columns"] == [*HEADERS, "Standard Reference"]


def test_the_contractor_columns_come_back_empty_rather_than_missing():
    """THEY BELONG TO THE CONTRACTOR, and the sheet has seven columns whether
    or not anyone has answered. Omitting them from the preview would hide the
    space the contractor fills; filling them would put words in their mouth."""
    doc = _submittal()
    run_id = _run(doc)
    _finding(doc, run_id, "NON_COMPLIANT")
    _finding(doc, run_id, "NEEDS_ENGINEER_REVIEW")

    body = _preview(_client(doc).get(f"/api/reviews/runs/{run_id}/crs/preview"))

    assert body["rows"], "the preview returned no rows to check"
    for row in body["rows"]:
        assert row["contractor_response"] == ""
        assert row["final_resolution"] == ""


def test_the_preview_is_the_workbook_row_for_row(monkeypatch):
    """THE POINT OF THE WHOLE FEATURE. Both renderings of one run, read back
    and compared cell by cell: the header block, the column headers, every
    data row across all seven columns, and the recommended code line.

    A company name is configured so row 1 carries real text: with none, the
    title is empty in both renderings and comparing nothing to nothing would
    prove nothing about the title.

    A preview that showed something other than the file the client receives
    would be worse than no preview at all, and the only reason this passes is
    that both routes compose through `_crs_content` and shape through
    `crs_export.build_crs_view`. Give either one its own builder and this
    test is what fails.
    """
    monkeypatch.setattr(settings, "crs_company_name", "EXAMPLE OPERATING COMPANY (EOC)")
    doc = _submittal(filename="P-1000001-2003-SP-0810-0003_00.pdf")
    _submittal("doc_std", "SAES-D-001.pdf")
    run_id = _run(doc)
    _finding(doc, run_id, "NON_COMPLIANT")
    _finding(doc, run_id, "NEEDS_ENGINEER_REVIEW", confirmed_by="eng")
    _finding(doc, run_id, "MISSING_INFORMATION")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,"
            "page_end,text,token_count,content_hash)"
            " VALUES ('c1',?,'drum.pdf',0,1,1,?,10,'h1')",
            (doc, "Per 32-SAMSS-004 the flanges shall comply throughout."))

    client = _client(doc, "doc_std")
    ws = _sheet(client.get(f"/api/reviews/runs/{run_id}/crs"))
    body = _preview(client.get(f"/api/reviews/runs/{run_id}/crs/preview"))

    # The header block, rows 1-7.
    assert ws.cell(row=1, column=1).value == body["title"]
    assert ws.cell(row=2, column=1).value == body["subtitle"]
    assert len(body["header"]) == len(HEADER_FIELDS)
    for offset, field in enumerate(body["header"]):
        assert _cell(ws, 3 + offset, 1) == field["label"]
        assert _cell(ws, 3 + offset, 3) == field["value"]

    # The column headers, directly under the header block.
    assert [_cell(ws, COLUMN_HEADER_ROW, c)
            for c in range(1, 10)] == body["columns"]

    # Every data row, from row 9, across all seven columns.
    assert len(body["rows"]) >= 3, "the fixture produced too few rows to prove"
    for row in body["rows"]:
        r = COLUMN_HEADER_ROW + row["item_no"]
        assert [_cell(ws, r, c) for c in range(1, 8)] == [
            row["item_no"], row["document_name"], row["page_section"],
            row["comment"], row["comment_by"], row["contractor_response"],
            row["final_resolution"]], f"row {row['item_no']} disagrees"
        assert _cell(ws, r, 8) == row["standard_reference"]
        assert _cell(ws, r, 9) == row["ai_review_comment"]
    # And no eighth row hiding in the workbook that the preview never showed.
    assert _cell(ws, COLUMN_HEADER_ROW + len(body["rows"]) + 1, 1) == ""

    # The recommended review code line.
    code_row = COLUMN_HEADER_ROW + len(body["rows"]) + 2
    assert _cell(ws, code_row, 1) == body["recommended_code_label"]
    assert _cell(ws, code_row, 3) == (
        f"{body['recommended_code']} - {body['recommended_code_reason']}")


def test_the_preview_shows_the_engineers_final_code_the_file_shows():
    """The CRS is what leaves the building, and the preview is what an
    engineer checks before it does. A signed code must appear in both."""
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

    body = _preview(_client(doc).get(f"/api/reviews/runs/{run_id}/crs/preview"))

    assert body["recommended_code"] == "Approved with Comments"
    assert body["recommended_code_reason"] == "both items are lookup tables"


def test_a_run_with_no_recommendation_previews_no_code_rather_than_a_guess():
    """Null renders as nothing (CLAUDE.md rule 4). An empty string here is a
    screen that prints nothing; a placeholder code would be a review the
    machine never gave."""
    doc = _submittal()
    run_id = _run(doc, recommended=None)

    body = _preview(_client(doc).get(f"/api/reviews/runs/{run_id}/crs/preview"))

    assert body["recommended_code"] == ""
    assert body["recommended_code_reason"] == ""


def test_the_preview_rejects_a_parameter_it_does_not_understand():
    """The same guard every other route carries: an unknown parameter is a
    caller believing something the route does not do."""
    doc = _submittal()
    run_id = _run(doc)

    response = _client(doc).get(
        f"/api/reviews/runs/{run_id}/crs/preview?include_responses=true")

    assert response.status_code == 422


# ================= the three fields the client asked for, end to end
#
# THROUGH THE ROUTE AND BACK OUT OF THE FILE. Each assertion below reads the
# rendered cell of a workbook the API actually produced, because a field that
# reaches `build_crs_view` and not the sheet is a field the client never gets.


def _number(doc_id: str, number: str) -> None:
    """Record the submittal's own transmittal number where upload puts it."""
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO document_classification (document_id, suggested_by,"
            " transmittal_number) VALUES (?,'upload',?)"
            " ON CONFLICT(document_id) DO UPDATE SET"
            " transmittal_number = excluded.transmittal_number", (doc_id, number))


def _submittal_no(ws) -> str:
    row = 3 + [k for _, k in HEADER_FIELDS].index("submittal_number")
    assert ws.cell(row=row, column=1).value == "Submittal No.:"
    return ws.cell(row=row, column=3).value


def test_the_submittal_number_on_the_sheet_is_the_submittals_own():
    """ITEM 1 OF THREE. Captured at upload, never exported until now - and it
    is NOT either transmittal number, which stay blank because nobody has
    issued one."""
    doc = _submittal()
    _number(doc, "EOC-SUB-2024-0417")
    run_id = _run(doc)

    ws = _sheet(_client(doc).get(f"/api/reviews/runs/{run_id}/crs"))

    assert _submittal_no(ws) == "EOC-SUB-2024-0417"
    assert ws.cell(row=3, column=3).value in (None, ""), "COMPANY transmittal"
    assert ws.cell(row=4, column=3).value in (None, ""), "CONTRACTOR transmittal"


def test_a_submittal_with_no_number_recorded_exports_a_blank_one():
    """NOT "None", NOT A PLACEHOLDER, and not a refusal to export. A
    submittal that was never classified has no metadata row at all."""
    doc = _submittal()
    run_id = _run(doc)

    ws = _sheet(_client(doc).get(f"/api/reviews/runs/{run_id}/crs"))

    assert _submittal_no(ws) in (None, "")


def test_the_page_section_column_carries_the_datasheet_page_and_field():
    """CRS QUICK WINS (audit crs.md defect 8): the client's "Page No./Section"
    column is where the CONTRACTOR looks for their page - it names the
    datasheet page, field and tag. The standard's name, clause and page moved
    to their own "Standard Reference" column."""
    doc = _submittal()
    _submittal("doc_std", "SAES-D-001.pdf")
    run_id = _run(doc)
    _finding(doc, run_id, "NON_COMPLIANT", matched_phrase="design pressure")

    ws = _sheet(_client(doc, "doc_std").get(f"/api/reviews/runs/{run_id}/crs"))

    assert ws.cell(row=COLUMN_HEADER_ROW, column=3).value == "Page No./Section"
    where = ws.cell(row=FIRST_DATA_ROW, column=3).value
    assert where == "p.4 - Design pressure (2003-47-V-0001A/B)"
    assert "SAES-D-001" not in where
    assert ws.cell(row=COLUMN_HEADER_ROW, column=8).value == "Standard Reference"
    assert ws.cell(row=FIRST_DATA_ROW, column=8).value == "SAES-D-001 cl. 6.2.2 (p.14)"


def _refs(ws) -> list[str]:
    """The reference line of every comment cell in the sheet, as rendered."""
    out = []
    for value in _cells(ws, 4):
        if value:
            first = str(value).split("\n")[0]
            assert first.startswith("Ref: RF-"), f"no reference on {first!r}"
            out.append(first)
    return out


def test_re_exporting_a_run_quotes_the_same_references():
    """ITEM 3 OF THREE, AND THE REQUIREMENT THAT MAKES IT WORTH HAVING. Two
    exports of one run, minutes or months apart: a contractor who answered
    RF-xxxxxx must find RF-xxxxxx again. `Item No` renumbers 1..N on every
    export and cannot carry this."""
    doc = _submittal()
    _submittal("doc_std", "SAES-D-001.pdf")
    run_id = _run(doc)
    _finding(doc, run_id, "NON_COMPLIANT")
    _finding(doc, run_id, "NEEDS_ENGINEER_REVIEW")
    client = _client(doc, "doc_std")

    first = _refs(_sheet(client.get(f"/api/reviews/runs/{run_id}/crs")))
    again = _refs(_sheet(client.get(f"/api/reviews/runs/{run_id}/crs")))

    assert len(first) == 2, first
    assert len(set(first)) == 2, "two rows shared one reference"
    assert first == again


def test_editing_a_finding_changes_the_reference_it_exports_under():
    """The counterpart. A rewritten comment is not the comment the
    contractor answered, and must not be quoted back under its number."""
    doc = _submittal()
    run_id = _run(doc)
    _finding(doc, run_id, "NON_COMPLIANT", id="f-known")
    client = _client(doc)

    before = _refs(_sheet(client.get(f"/api/reviews/runs/{run_id}/crs")))
    with db.connect() as conn:
        conn.execute("UPDATE review_findings SET contractor_evidence_text ="
                     " '690 kPa' WHERE id = 'f-known'")
    after = _refs(_sheet(client.get(f"/api/reviews/runs/{run_id}/crs")))

    assert before and before != after


def test_the_reference_the_preview_shows_is_the_one_in_the_file():
    """ONE BUILDER, TWO RENDERINGS - including the reference. An engineer
    reading a number off the screen must be reading the contractor's copy."""
    doc = _submittal()
    run_id = _run(doc)
    _finding(doc, run_id, "NON_COMPLIANT")
    client = _client(doc)

    ws = _sheet(client.get(f"/api/reviews/runs/{run_id}/crs"))
    body = _preview(client.get(f"/api/reviews/runs/{run_id}/crs/preview"))

    assert body["rows"], "the preview returned no rows to check"
    for row in body["rows"]:
        cell = ws.cell(row=COLUMN_HEADER_ROW + row["item_no"], column=4).value
        assert row["row_ref"].startswith("RF-")
        assert str(cell).split("\n")[0] == f"Ref: {row['row_ref']}"


def test_the_additions_left_the_seven_template_columns_in_place():
    """P0-5. The client's seven template columns keep their order and names;
    the row reference rides in the comment text. CRS quick wins (2026-09-27)
    adds ONE column after them in both copies, "Standard Reference" (the
    brief's order: the standard in its own column) - a widening the client
    has to sign off, flagged in the change's report."""
    doc = _submittal()
    _number(doc, "EOC-SUB-2024-0417")
    run_id = _run(doc)
    _finding(doc, run_id, "NON_COMPLIANT")
    # The issue-copy gate (safety group, 2026-09-27) requires an engineer's
    # final code before this copy may be exported - not what this test is
    # about, so it is satisfied here rather than worked around.
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET engineer_final_code='Approved'"
                     " WHERE id = ?", (run_id,))

    # The copy ISSUED to the contractor is the template's seven columns plus
    # "Standard Reference"; the internal review copy adds "AI Review
    # Comments", last (owner decision 2026-09-27), and moves no other column.
    ws = _sheet(_client(doc).get(f"/api/reviews/runs/{run_id}/crs", params={"copy": "issue"}))
    internal = _sheet(_client(doc).get(f"/api/reviews/runs/{run_id}/crs"))
    assert [internal.cell(row=COLUMN_HEADER_ROW, column=c).value
            for c in range(1, 10)] == [*HEADERS, "Standard Reference", "AI Review Comments"]

    assert [ws.cell(row=COLUMN_HEADER_ROW, column=c).value
            for c in range(1, 9)] == [*HEADERS, "Standard Reference"]
    assert ws.max_column == 8


def test_the_issue_copy_is_refused_until_an_engineer_decides():
    """SAFETY GROUP (2026-09-27). A copy meant to leave the building must
    carry a human's decision, not just the machine's recommendation. With no
    `engineer_final_code` on the run, `copy=issue` is refused with 409 - the
    same rule the frontend enforces by disabling the button
    (`ReviewRunsView.tsx`)."""
    doc = _submittal()
    run_id = _run(doc)
    _finding(doc, run_id, "NON_COMPLIANT")

    response = _client(doc).get(f"/api/reviews/runs/{run_id}/crs",
                                 params={"copy": "issue"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "code_not_decided"

    # The internal copy is unaffected by the same gate.
    assert _client(doc).get(f"/api/reviews/runs/{run_id}/crs").status_code == 200

    # Once an engineer records the final code, the issue copy is allowed.
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET engineer_final_code='Approved'"
                     " WHERE id = ?", (run_id,))
    assert _client(doc).get(f"/api/reviews/runs/{run_id}/crs",
                            params={"copy": "issue"}).status_code == 200
