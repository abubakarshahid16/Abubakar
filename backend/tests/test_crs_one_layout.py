"""Order 13, part B: the normal reviewer's CRS in the one layout (ten columns, Status, Evidence, Notes), the Status mapping over every
row kind, and the reply reader finding its columns by header name in the new layout AND in an old-layout file. Invented data only."""

from __future__ import annotations

import io

import openpyxl
import pytest

from app import crs_ai_words as words
from app import crs_export, crs_layout, crs_mapping, crs_normal, crs_reply

TEN = [
    "Item No", "Document Name", "Page No./Section", "COMPANY Comments", "Comment By", "Contractor's Response",
    "Final Resolution", "Standard Reference", "Priority", "Status",
]  # fmt: skip


def _rows():
    base = {
        "document_name": "DS-1.pdf",
        "comment_by": "Engineer",
        "engineer_confirmed": True,
        "standard_reference": "STD-1 4.1",
        "reasoning": "Read: x.",
        "rule_trust": "automatic (proven rule)",
        "ai_review_comment": "AI wording",
    }
    return [
        {
            **base,
            "page_section": "p.1",
            "comment": "Above the limit.",
            "row_kind": "non_compliant",
            "priority": 1,
        },
        {
            **base,
            "page_section": "p.2",
            "comment": "Value missing.",
            "row_kind": "missing_information",
            "priority": 2,
        },
        {
            **base,
            "page_section": "p.3",
            "comment": "An AI draft.",
            "row_kind": "ai_engineering_check",
            "priority": 3,
        },
        {
            **base,
            "page_section": "p.4",
            "comment": "A tick.",
            "row_kind": "safety_tick",
            "priority": 3,
        },
    ]


def _book(copy="internal", rows=None, meta=None):
    meta = {"review_run_id": "r", "copy": copy, "export_quality": False, **(meta or {})}
    data = crs_export.build_crs(rows or _rows(), meta)
    return openpyxl.load_workbook(io.BytesIO(data))


def _table(ws):
    top = next(r for r in range(1, 40) if ws.cell(r, 1).value == "Item No")
    head = [c.value for c in ws[top]]
    return [
        dict(zip(head, [c.value for c in ws[r]], strict=False))
        for r in range(top + 1, top + 1 + 4)
    ]


def test_the_normal_reviewers_sheet_has_the_ten_columns_in_the_one_layouts_order():
    ws = _book("internal")["CRS"]
    assert [c.value for c in ws[crs_export.COLUMN_HEADER_ROW]][:10] == TEN
    assert ws.max_column == 10
    assert (
        ws.freeze_panes == f"A{crs_export.COLUMN_HEADER_ROW + 1}"
        and ws.page_setup.orientation == "landscape"
    )
    assert ws.cell(crs_export.COLUMN_HEADER_ROW, 1).fill.fgColor.rgb == "FF1F3864"


def test_the_contractor_facing_copy_has_the_nine_company_columns_the_old_header_and_plain_styling():
    """Blocking 1 of R30: an issued comment is the company's; a Status (or a colour for it) would say which were drafts."""
    wb = _book("issue")
    ws = wb["CRS"]
    assert [c.value for c in ws[crs_export.ISSUE_HEADER_ROW]] == TEN[:9]
    assert ws.max_column == 9 and "Status" not in str(
        [c.value for r in ws.iter_rows() for c in r]
    )
    labels = [ws.cell(r, 1).value for r in range(3, crs_export.ISSUE_HEADER_ROW)]
    assert labels == [
        label for label, _key in crs_export.HEADER_FIELDS
    ]  # exactly the header it had before
    body = [c for r in ws.iter_rows(min_row=crs_export.ISSUE_HEADER_ROW + 1) for c in r]
    assert all(
        c.fill.fill_type is None for c in body
    )  # no colour encodes a Status or a row kind
    banned = (
        "AI opinion",
        "Query",
        "AI verdict",
        "AI reviewer's view",
        "not proven",
    )
    for sheet in wb.worksheets:
        for row in sheet.iter_rows(values_only=True):
            for value in row:
                assert not any(b in str(value or "") for b in banned), value


def test_its_comment_texts_order_and_numbers_are_what_they_were_only_moved():
    rows = _table(_book()["CRS"])
    assert [r["COMPANY Comments"] for r in rows] == [
        "Above the limit.",
        "Value missing.",
        "An AI draft.",
        "A tick.",
    ]
    assert [r["Item No"] for r in rows] == [1, 2, 3, 4]
    assert [r["Comment By"] for r in rows] == ["Engineer"] * 4  # what it writes today
    assert [r["Standard Reference"] for r in rows] == ["STD-1 4.1"] * 4


def test_status_and_priority_by_the_stated_rule():
    rows = _table(_book()["CRS"])
    assert [(r["Status"], r["Priority"]) for r in rows] == [
        ("Fail", "High"), ("Query", "Low"), ("AI opinion", "Medium"), ("Pass", None),
    ]  # fmt: skip


def test_the_working_columns_are_on_the_evidence_sheet_and_the_notes_counts_equal_the_rows():
    wb = _book()
    assert wb.sheetnames[:3] == ["CRS", "Evidence", "Notes"]
    ev = list(wb["Evidence"].iter_rows(min_row=2, values_only=True))
    assert [(e[0], e[1], e[2]) for e in ev] == [
        (1, "Fail", "non_compliant"), (2, "Query", "missing_information"), (3, "AI opinion", "ai_engineering_check"),
        (4, "Pass", "safety_tick"),
    ]  # fmt: skip
    assert (
        ev[0][3] == "Out of limit"
        and ev[0][5] == "AI wording"
        and ev[0][6] == "Read: x."
        and ev[0][7] == "automatic (proven rule)"
    )
    notes = {r[0]: r[1] for r in wb["Notes"].iter_rows(min_row=2, values_only=True)}
    assert (
        notes["Priority rule"] == words.PRIORITY_RULE
        and "safety tick" in notes["Status mapping"]
    )
    assert [notes[f"Count: {s}"] for s in words.STATUSES] == [1, 1, 1, 1]
    assert notes["Count: rows on the CRS sheet"] == 4


def test_the_issue_copy_carries_no_evidence_no_notes_and_no_generated_by_sentence():
    wb = _book("issue")
    assert "Evidence" not in wb.sheetnames and "Notes" not in wb.sheetnames
    text = "\n".join(
        str(c)
        for ws in wb.worksheets
        for r in ws.iter_rows(values_only=True)
        for c in r
        if c is not None
    )
    assert (
        "Generated by AI" not in text
        and "AI wording" not in text
        and "Read: x." not in text
    )
    assert "Generated by AI, to be confirmed by a COMPANY engineer" in "\n".join(
        str(c)
        for r in _book("internal")["CRS"].iter_rows(values_only=True)
        for c in r
        if c
    )


def test_the_header_block_takes_the_documents_facts_from_the_meta_and_keeps_the_older_fields():
    meta = {"header": {"project": "P", "document_number": "N-1", "title": "T", "revision": "B", "date": "2026-01-02",
                       "discipline": "instrument"}, "company_transmittal": "CT-1"}  # fmt: skip
    ws = _book(meta=meta)["CRS"]
    got = {
        ws.cell(r, 1).value: ws.cell(r, 3).value
        for r in range(3, crs_export.COLUMN_HEADER_ROW)
    }
    assert (
        got["Project:"] == "P"
        and got["Document number:"] == "N-1"
        and got["Revision:"] == "B"
    )
    assert got["Date:"] == "2026-01-02" and got["Discipline:"] == "instrument"
    assert got["COMPANY Transmittal No.:"] == "CT-1"
    blank = _book()["CRS"]
    assert blank.cell(crs_export.HEADER_ROW_OF["company_transmittal"], 3).value in (
        None,
        "",
    )


def test_every_row_kind_and_rank_maps_to_one_of_the_four_words_and_a_pass_or_fail_is_only_its_own_kind():
    """Brute force: every ROW_KIND_* constant (and the two kinds only the exporter knows) x every rank."""
    kinds = {v for k, v in vars(crs_mapping).items() if k.startswith("ROW_KIND_")} | {
        "clause_review",
        "spec_kit",
        "made_up",
        None,
    }
    ranks = [None, 0, 1, 2, 3, 4, 5]
    assert len(kinds) >= 15
    for kind in kinds:
        for rank in ranks:
            status = crs_normal.crs_status(kind, rank)
            assert status in words.STATUSES, (kind, rank)
            if kind in (
                "ai_engineering_check",
                "web_standard_check",
                "clause_review",
                "spec_kit",
            ):
                assert status == "AI opinion", (
                    kind,
                    rank,
                )  # an AI draft is never a Pass or a Fail
            elif kind == "safety_tick":
                assert status == "Pass"
            else:
                # Fail needs a kind whose rank 1 is a figure code compared (listed once: CODE_COMPARED_KINDS); an unknown kind is a
                # Query at every rank, rank 1 included
                assert (status == "Fail") == (
                    kind in crs_normal.CODE_COMPARED_KINDS
                    and rank == crs_mapping.PRIORITY_OUT_OF_LIMIT
                ), (kind, rank)  # Fail = a figure code compared


def test_a_row_the_exporter_does_not_know_is_a_query_never_a_pass_or_a_fail():
    assert (
        crs_normal.crs_status("made_up", crs_mapping.PRIORITY_ENGINEERS_COMMENT)
        == "Query"
    )
    assert crs_normal.crs_status(None, None) == "Query"


# ---------------------------------------------------------------- the reply reader: by header name, either layout


def _reply_book(layout):
    """A returned sheet whose columns are NOT where the exporter puts them: a column of the contractor's own is inserted before Item No,
    and Contractor's Response is moved to the front of the others, so a reader that took fixed columns would read the wrong cells."""
    wb = openpyxl.Workbook()
    ws = wb.active
    if (
        layout == "old"
    ):  # the seven-column template with its header block, header on row 9
        top, head = (
            9,
            [
                "Item No",
                "Document Name",
                "Page No./Section",
                "COMPANY Comments",
                "Comment By",
                "Contractor's Response",
                "Final Resolution",
            ],
        )
    else:  # the new layout: a taller header block, ten columns
        top, head = 17, list(TEN)
    head.remove("Contractor's Response")
    head = [
        "Contractor tag",
        "Contractor's Response",
        *head,
    ]  # inserted column first, the response second
    for r in range(1, top):
        ws.cell(r, 1, f"block {r}")
    for c, name in enumerate(head, start=1):
        ws.cell(top, c, name)
    item, resp, name = (
        head.index("Item No") + 1,
        head.index("Contractor's Response") + 1,
        head.index("Document Name") + 1,
    )
    for n, (ref, text) in enumerate(
        (("CRS-INV-001", "Accepted - done"), ("CRS-INV-002", "Rejected - no")), start=1
    ):
        ws.cell(top + n, 1, "tag")
        ws.cell(top + n, item, ref)
        ws.cell(top + n, resp, text)
        ws.cell(top + n, name, "paper.pdf")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.parametrize("layout", ["old", "new"])
def test_the_reply_reader_finds_its_columns_by_header_name_in_either_layout(layout):
    got = crs_reply.read_replies(_reply_book(layout))
    assert [(r["item"], r["response"]) for r in got] == [
        ("CRS-INV-001", "Accepted - done"),
        ("CRS-INV-002", "Rejected - no"),
    ]
    assert got[0]["document_name"] == "paper.pdf"


def test_the_reply_reader_reads_a_workbook_this_exporter_wrote():
    rows = [
        {
            **r,
            "crs_ref": f"CRS-INV-00{i}",
            "crs_response": "Accepted - ok" if i == 1 else "",
        }
        for i, r in enumerate(_rows(), 1)
    ]
    data = crs_export.build_crs(
        rows, {"review_run_id": "r", "copy": "issue", "export_quality": False}
    )
    got = crs_reply.read_replies(data)
    assert [r["item"] for r in got] == [f"CRS-INV-00{i}" for i in range(1, 4)] and got[
        0
    ]["response"] == "Accepted - ok"


def test_the_one_layouts_drawing_code_is_shared():
    assert crs_layout.LAYOUT_COLUMNS == tuple(TEN)


def test_both_copies_of_one_review_print_the_same_priority_per_item_no():
    """One vocabulary (lead): the Priority of a row is the stated rule's word on the internal AND the issue copy."""
    internal = {r["Item No"]: r["Priority"] for r in _table(_book("internal")["CRS"])}
    issue = {
        r["Item No"]: r["Priority"]
        for r in _table(_book("issue")["CRS"])
        if r["Item No"]
    }
    assert issue and all(internal[k] == v for k, v in issue.items())
    assert set(issue.values()) <= {"High", "Medium", "Low", None}
