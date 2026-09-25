"""Tests for the CRS generator. Standalone: no db, no app fixtures.

Written and first run by Cowork against the client's real template shape;
9 tests. The structural assertions (headers, merges) ARE the spec - they
were measured from CRS - Form of Agreement_2028 1.xlsx, not invented.
"""
import io

import openpyxl

from app.crs_export import (COLUMN_HEADER_ROW, FIRST_DATA_ROW,
                            HEADER_FIELDS, HEADERS, build_crs)

META = {"project": "EXAMPLE PROJECT", "document_title": "Doc T",
        "date_issued": "2026-09-19"}


def load(findings, meta=META):
    return openpyxl.load_workbook(io.BytesIO(build_crs(findings, meta))).active


def test_headers_match_the_client_template_exactly():
    ws = load([])
    assert [ws.cell(row=COLUMN_HEADER_ROW, column=c).value
            for c in range(1, 8)] == HEADERS


def test_the_contractor_columns_are_always_empty():
    ws = load([{"document_name": "d", "page_section": "p",
                "comment": "c", "comment_by": "b"}])
    assert ws.cell(row=FIRST_DATA_ROW, column=6).value in (None, "")
    assert ws.cell(row=FIRST_DATA_ROW, column=7).value in (None, "")


def test_item_numbers_are_assigned_1_to_n_with_no_gaps():
    ws = load([{"comment": f"c{i}"} for i in range(5)])
    assert [ws.cell(row=COLUMN_HEADER_ROW + n, column=1).value
            for n in (1, 2, 3, 4, 5)] == [1, 2, 3, 4, 5]


def test_the_header_block_carries_the_meta():
    ws = load([], {"project": "DFDP", "document_title": "Sour Water Drums",
                   "company_transmittal": "EOC-TX-001",
                   "date_issued": "2026-09-19"})
    keys = [key for _, key in HEADER_FIELDS]
    assert "DFDP" in ws.cell(row=1, column=1).value
    assert ws.cell(row=2, column=1).value == "COMMENT RESOLUTION SHEET"
    assert ws.cell(row=3 + keys.index("company_transmittal"),
                   column=3).value == "EOC-TX-001"
    assert ws.cell(row=3 + keys.index("document_title"),
                   column=3).value == "Sour Water Drums"


def test_missing_meta_renders_as_nothing_never_none_text():
    ws = load([], {"project": "X"})
    keys = [key for _, key in HEADER_FIELDS]
    for row in (3 + keys.index(key) for key in keys if key != "project"):
        value = ws.cell(row=row, column=3).value
        assert value in (None, ""), f"row {row} leaked {value!r}"


def test_empty_findings_yield_a_valid_sheet_with_no_data_rows():
    ws = load([])
    assert ws.cell(row=FIRST_DATA_ROW, column=1).value is None


def test_merges_match_the_template_shape():
    ws = load([])
    merges = {str(r) for r in ws.merged_cells.ranges}
    for merge in ("A1:G1", "A2:G2", "A3:B3", "C3:G3", "A7:B7", "C7:G7"):
        assert merge in merges


def test_a_long_comment_gets_a_taller_row():
    short = load([{"comment": "short"}]).row_dimensions[FIRST_DATA_ROW].height
    long_ = load([{"comment": "x" * 400}]).row_dimensions[FIRST_DATA_ROW].height
    assert long_ > short


def test_every_data_cell_is_bordered():
    ws = load([{"comment": "c"}])
    for col in range(1, 8):
        assert ws.cell(row=FIRST_DATA_ROW, column=col).border.top.style == "thin"


def test_recommended_code_renders_with_its_reason():
    ws = load([{"comment": "c"}],
              dict(META, recommended_code="Manual Review Required",
                   recommended_code_reason="governing standards not available"))
    code_row = COLUMN_HEADER_ROW + 1 + 2
    value = ws.cell(row=code_row, column=3).value
    assert "Manual Review Required" in value
    assert "governing standards" in value
    assert ws.cell(row=code_row, column=1).value == "Recommended Review Code:"


def test_no_code_no_row():
    ws = load([{"comment": "c"}])
    assert ws.cell(row=COLUMN_HEADER_ROW + 3, column=1).value is None


# ============================ issue #165 criterion 4: visual distinction

def test_rows_of_different_kinds_get_different_fill_colours():
    """CRITERION 4. Opened with openpyxl, not asserted against the view dict
    - the same discipline section 12 of the audit demanded for the other
    three fields: read back what the file actually says, not what the
    builder meant to say."""
    ws = load([
        {"comment": "a defect", "row_kind": "non_compliant"},
        {"comment": "needs a human", "row_kind": "needs_engineer_review"},
        {"comment": "no value stated", "row_kind": "missing_information"},
        {"comment": "check elsewhere", "row_kind": "requires_other_document"},
    ])
    fills = [ws.cell(row=FIRST_DATA_ROW + n, column=4).fill.fgColor.rgb
             for n in range(4)]
    assert len(set(fills)) == 4, f"rows did not get 4 distinct fills: {fills}"
    assert all(f not in (None, "00000000") for f in fills)


def test_a_row_with_no_kind_gets_no_fill():
    """A raw dict from before #165 (no `row_kind` key) must still render - no
    fill is the honest default, not a guessed one."""
    ws = load([{"comment": "plain"}])
    cell = ws.cell(row=FIRST_DATA_ROW, column=4)
    assert cell.fill.fgColor.rgb in (None, "00000000")


# ====================== the three fields the client asked for, as rendered
#
# READ BACK OUT OF THE WORKBOOK, NOT OFF THE VIEW. A test that asserted
# against `build_crs_view`'s dict would pass over a renderer that dropped the
# value on the floor - which is the defect section 12 of the audit named:
# "verified by opening the file" that checked presence and spelling, never
# truth, and let six false rows ship.

SUB = {"project": "EXAMPLE PROJECT", "document_title": "Doc T",
       "date_issued": "2026-09-19", "review_run_id": "run_1",
       "company_transmittal": "EOC-TX-001",
       "contractor_transmittal": "CTR-TX-009",
       "submittal_number": "SUB-2024-0417"}

FINDING = {"document_name": "drum.pdf", "page_section": "SAES-D-001 clause 6.2.2",
           "comment": "Requirement: 6,900 kPa\nSubmitted: 2.2 bar (ga)",
           "comment_by": "AI Review", "finding_id": "f-1"}


def _header_row(key: str) -> int:
    return 3 + [k for _, k in HEADER_FIELDS].index(key)


def _comment(ws, item_no: int = 1) -> str:
    return ws.cell(row=COLUMN_HEADER_ROW + item_no, column=4).value


def test_the_submittal_number_is_printed_in_the_header_block():
    """ITEM 1. The submittal's own number, in the cell, under its own label."""
    ws = load([], SUB)
    row = _header_row("submittal_number")
    assert ws.cell(row=row, column=1).value == "Submittal No.:"
    assert ws.cell(row=row, column=3).value == "SUB-2024-0417"


def test_the_submittal_number_is_beside_the_two_transmittals_not_either_of_them():
    """THREE DIFFERENT NUMBERS. The covering transmittals name who sent what
    to whom; the submittal number names the document under review. A sheet
    that reused either would tell the contractor the wrong document was
    reviewed, and it would look entirely plausible."""
    ws = load([], SUB)
    values = {ws.cell(row=_header_row(k), column=3).value
              for k in ("company_transmittal", "contractor_transmittal",
                        "submittal_number")}
    assert values == {"EOC-TX-001", "CTR-TX-009", "SUB-2024-0417"}


def test_a_submittal_with_no_number_prints_nothing_not_none():
    """The rule the rest of the header block already follows. A CRS carrying
    an invented number lies about its own provenance."""
    ws = load([], {"project": "X", "review_run_id": "run_1"})
    assert ws.cell(row=_header_row("submittal_number"), column=3).value in (None, "")


def test_the_row_reference_is_the_first_line_of_the_comment_cell():
    """ITEM 3, AND NO EIGHTH COLUMN. The client's template has seven columns;
    the reference rides in the COMPANY Comments text, above the comment
    itself, in the shape the Requirement/Submitted lines already use."""
    ws = load([FINDING], SUB)
    lines = _comment(ws).split("\n")
    assert lines[0].startswith("Ref: RF-"), lines[0]
    assert lines[1] == "Requirement: 6,900 kPa"
    assert ws.cell(row=COLUMN_HEADER_ROW, column=8).value is None
    assert [ws.cell(row=COLUMN_HEADER_ROW, column=c).value
            for c in range(1, 8)] == HEADERS


def test_re_exporting_the_same_review_prints_the_same_reference():
    """THE HARD REQUIREMENT. A contractor answering RF-xxxxxx has to find
    RF-xxxxxx on the next sheet. Two independent exports of the same content,
    read out of the two workbooks."""
    first = _comment(load([FINDING, dict(FINDING, finding_id="f-2",
                                         comment="Submitted: 13 mm")], SUB))
    again = _comment(load([FINDING, dict(FINDING, finding_id="f-2",
                                         comment="Submitted: 13 mm")], SUB))
    assert first.split("\n")[0] == again.split("\n")[0]
    assert first.split("\n")[0] != "Ref: RF-"


def test_the_reference_does_not_move_when_the_row_does():
    """NOT DERIVED FROM POSITION. The same finding exported second rather
    than first keeps its number - `Item No` is the column that renumbers."""
    other = dict(FINDING, finding_id="f-2", comment="Submitted: 13 mm")
    alone = _comment(load([FINDING], SUB)).split("\n")[0]
    second = _comment(load([other, FINDING], SUB), item_no=2).split("\n")[0]
    assert alone == second


def test_a_finding_that_genuinely_changes_gets_a_different_reference():
    """THE OTHER HALF OF THE BARGAIN. A rewritten comment is a different
    comment, and quoting it back under the old number would attach the
    contractor's answer to text they never read."""
    before = _comment(load([FINDING], SUB)).split("\n")[0]
    after = _comment(load([dict(FINDING, comment="Submitted: 690 kPa")],
                          SUB)).split("\n")[0]
    assert before != after


def test_confirming_a_finding_does_not_renumber_it():
    """An engineer confirming changes WHO SAYS IT, not what it says. The
    Comment By column carries that; the reference must not move for it."""
    plain = _comment(load([FINDING], SUB)).split("\n")[0]
    confirmed = _comment(load(
        [dict(FINDING, comment_by="AI Review, confirmed by eng")], SUB)
    ).split("\n")[0]
    assert plain == confirmed


def test_the_same_finding_in_a_different_run_gets_a_different_reference():
    """The run is half the key: two reviews of one submittal are two sheets,
    and one number meaning both would make a reply ambiguous."""
    one = _comment(load([FINDING], SUB)).split("\n")[0]
    two = _comment(load([FINDING], dict(SUB, review_run_id="run_2"))).split("\n")[0]
    assert one != two


def test_two_identical_rows_still_get_two_distinct_references():
    """A reference a contractor cannot answer unambiguously is worse than no
    reference. Identical text is re-minted rather than repeated."""
    twin = dict(FINDING, finding_id="")
    ws = load([twin, dict(twin)], SUB)
    assert _comment(ws, 1).split("\n")[0] != _comment(ws, 2).split("\n")[0]


def test_a_row_with_no_comment_still_carries_its_reference():
    """A gap row with empty text must still be answerable by number, and must
    not open with a stray blank line."""
    ws = load([{"document_name": "d", "page_section": "References",
                "comment": "", "finding_id": "missing-reference:X"}], SUB)
    value = _comment(ws)
    assert value.startswith("Ref: RF-") and "\n" not in value


# ------------------------------------------------ the company name is config

def test_the_default_company_comes_from_settings(monkeypatch):
    """THE MUTATION TARGET (M540). The company printed on row 1 when the
    caller names none is read from `settings.crs_company_name` (env
    CRS_COMPANY_NAME) - a client identifier kept in `.env`, not in git."""
    from app.config import settings
    from app.crs_export import build_crs_view
    monkeypatch.setattr(settings, "crs_company_name", "EXAMPLE OPERATING COMPANY (EOC)")
    view = build_crs_view([], {"project": "EXAMPLE PROJECT"})
    assert view["title"] == "EXAMPLE OPERATING COMPANY (EOC)\n EXAMPLE PROJECT"
    ws = load([], {"project": "EXAMPLE PROJECT"})
    assert ws.cell(row=1, column=1).value.startswith("EXAMPLE OPERATING COMPANY (EOC)")


def test_an_unset_company_prints_nothing_rather_than_a_guess(monkeypatch):
    """Empty is the default, and empty prints nothing - no invented company,
    and no stray blank line in front of the project."""
    from app.config import settings
    from app.crs_export import build_crs_view
    monkeypatch.setattr(settings, "crs_company_name", "")
    assert build_crs_view([], {"project": "EXAMPLE PROJECT"})["title"] == "EXAMPLE PROJECT"
    assert build_crs_view([], {})["title"] == ""
