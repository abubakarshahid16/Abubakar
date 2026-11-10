"""Owner order 11 Nov 2026, owner answer (#805): ONE "By Contractor" query row on the CONTRACTOR copy, behind
CRS_BY_CONTRACTOR_ONE_ROW_ENABLED (off). The rows held because the sheet marks a value as deferred (hold reason
`deferred_marker`) become one query row on the issue copy, every field still named with its tag and page; the
internal copy keeps one row per field; a row with the engineer's own words keeps its own row. Switch off: every
export path as on main. Invented findings only; no model, no database."""

from __future__ import annotations

import io

import openpyxl
import pytest

from app import crs_by_contractor as bc
from app import crs_export, crs_numbers, hold_reason
from app.config import settings
from app.crs_mapping import build_crs_rows

HELD = "NEEDS_ENGINEER_REVIEW"


def finding(
    n: int, *, code=hold_reason.DEFERRED_MARKER, tag="Q-7", page=None, **over
) -> dict:
    """One invented datasheet-check finding, held as a query with stored hold reason `code`."""
    base = {
        "id": f"fid-{n}",
        "origin": "datasheet_check",
        "compliance_status": HELD,
        "hold_reason_code": code,
        "requirement_source_text": f"DATASHEET CHECK INV-{n}: invented item {n} is stated",
        "standard_clause": f"9.{n}",
        "crs_field_label": f"Invented quantity {n}",
        "contractor_section": f"Invented quantity {n}",
        "contractor_evidence_text": f"{n}0 zorbs",
        "contractor_page": page if page is not None else n,
        "equipment_tag": tag,
        "document_id": "doc-inv",
        "approval_status": "accepted",
        "approved_by": "user-inv",
        "finding": f"Invented finding {n}",
    }
    return {**base, **over}


BREACH = {
    "id": "fid-99",
    "origin": "datasheet_check",
    "compliance_status": "NON_COMPLIANT",
    "requirement_source_text": "DATASHEET CHECK INV-99: invented limit not more than 5 zorbs",
    "crs_field_label": "Invented limit",
    "contractor_section": "Invented limit",
    "contractor_evidence_text": "9 zorbs",
    "contractor_page": 1,
    "equipment_tag": "Q-7",
    "document_id": "doc-inv",
    "approval_status": "accepted",
    "approved_by": "user-inv",
    "finding": "Invented breach",
}

DEFERRED = [finding(1, page=2), finding(2, tag="Q-8", page=3), finding(3, page=3)]


def switch(monkeypatch, value: bool) -> None:
    monkeypatch.setattr(settings, "crs_by_contractor_one_row_enabled", value)


def rows_of(findings):
    return build_crs_rows([dict(f) for f in findings], [], "Invented sheet.pdf")


def view(rows, copy):
    return crs_export.build_crs_view(
        [dict(r) for r in rows],
        {"review_run_id": "run-inv", "copy": copy, "export_quality": False},
    )


def comments(v) -> list[str]:
    return [r["comment"] for r in v["rows"]]


def cells(data: bytes) -> list[list]:
    wb = openpyxl.load_workbook(io.BytesIO(data))
    return [[list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets]


# ------------------------------------------------------------ the mapping half


def test_switch_off_no_row_carries_the_deferred_entries(monkeypatch):
    switch(monkeypatch, False)
    rows = rows_of([*DEFERRED, BREACH])
    assert len(rows) == 4
    assert not any(bc.KEY in r for r in rows)


def test_switch_on_each_deferred_row_carries_its_field_tag_and_page(monkeypatch):
    switch(monkeypatch, True)
    rows = rows_of([*DEFERRED, BREACH])
    marked = [r for r in rows if bc.KEY in r]
    assert len(marked) == 3
    entries = [e for r in marked for e in r[bc.KEY]]
    assert {(e["finding_id"], e["field"], e["tag"], e["page"]) for e in entries} == {
        ("fid-1", "Invented quantity 1", "Q-7", "p.2"),
        ("fid-2", "Invented quantity 2", "Q-8", "p.3"),
        ("fid-3", "Invented quantity 3", "Q-7", "p.3"),
    }


@pytest.mark.parametrize(
    "over",
    [
        {"hold_reason_code": hold_reason.RULE_NOT_PROVEN},
        {"hold_reason_code": None},
        {"compliance_status": "NON_COMPLIANT"},
        {"engineer_comment": "Invented engineer words"},
        {"id": ""},
        {"crs_field_label": "", "contractor_section": ""},
    ],
    ids=["other_code", "no_code", "decided", "engineer_words", "no_id", "no_field"],
)
def test_a_row_not_held_only_for_a_deferred_value_carries_no_entry(monkeypatch, over):
    switch(monkeypatch, True)
    (row,) = rows_of([finding(4, **over)])
    assert bc.KEY not in row


def test_a_row_standing_on_one_deferred_and_one_other_finding_carries_no_entry(
    monkeypatch,
):
    switch(monkeypatch, True)
    group = [finding(5), finding(6, code=hold_reason.OTHER)]
    assert bc.fields(group, lambda f: "Invented", lambda f: "p.1") is None


# ------------------------------------------------------------ the export half


def issue_rows(monkeypatch, findings, on: bool):
    """The rows the issue copy is built from, made with the switch `on`, as if an engineer confirmed each
    (the issue copy prints only those)."""
    switch(monkeypatch, on)
    return [{**r, "engineer_confirmed": True} for r in rows_of(findings)]


def test_switch_on_the_contractor_copy_has_one_query_row_naming_every_field(
    monkeypatch,
):
    rows = issue_rows(monkeypatch, [*DEFERRED, BREACH], True)
    single = [r for r in rows if bc.KEY in r]
    v = view(rows, crs_export.COPY_ISSUE)
    assert len(v["rows"]) == 2  # the breach, then one query row for three deferred rows
    query = [c for c in comments(v) if bc.LEAD in c]
    assert len(query) == 1
    lines = query[0].split("\n")
    lines = lines[
        lines.index(bc.LEAD) :
    ]  # an unnumbered issue row opens with its "Ref:" line
    # NO ROW IS LOST: every field, tag and page of every individual row is on its own line
    for r in single:
        for e in r[bc.KEY]:
            assert any(
                e["field"] in ln and f"tag {e['tag']}" in ln and e["page"] in ln
                for ln in lines
            ), e
    assert len([ln for ln in lines if ln.startswith("- ")]) == 3


def test_the_query_row_takes_the_first_members_place_and_number(monkeypatch):
    rows = issue_rows(monkeypatch, [*DEFERRED, BREACH], True)
    late = {
        k: v for k, v in rows[0].items() if k != bc.KEY
    }  # a plain row after the deferred ones
    rows.append({**late, "finding_id": "fid-late", "finding_ids": ["fid-late"]})
    rows = [
        {**r, "crs_ref": f"CRS-INV-00{i}", "crs_status": "Open"}
        for i, r in enumerate(rows, 1)
    ]
    first = next(i for i, r in enumerate(rows) if bc.KEY in r)
    v = view(rows, crs_export.COPY_ISSUE)
    query = next(r for r in v["rows"] if bc.LEAD in r["comment"])
    assert v["rows"].index(query) == first
    # Item No: every member's number, the first member's first, one per line
    assert query["item_no"] == "\n".join(r["crs_ref"] for r in rows if bc.KEY in r)
    assert query["item_no"].split("\n")[0] == rows[first]["crs_ref"]
    for r in rows:
        if bc.KEY in r:  # every member's own number stays on its line
            assert r["crs_ref"] in query["comment"]


def test_switch_on_the_internal_copy_keeps_one_row_per_field(monkeypatch):
    rows = issue_rows(monkeypatch, [*DEFERRED, BREACH], True)
    v = view(rows, crs_export.COPY_INTERNAL)
    assert len(v["rows"]) == 4
    assert not any(bc.LEAD in c for c in comments(v))


@pytest.mark.parametrize(
    "over",
    [
        {"edited": True, "comment": "Invented words the engineer wrote"},
        {"crs_response": "Invented contractor reply"},
        {"crs_status": "Closed - invented note"},
    ],
    ids=["edit", "answer", "shut"],
)
def test_a_row_with_the_engineers_words_a_reply_or_a_closed_number_keeps_its_own_row(
    monkeypatch, over
):
    rows = issue_rows(monkeypatch, [*DEFERRED, BREACH], True)
    keep = next(i for i, r in enumerate(rows) if bc.KEY in r)
    rows[keep] = {**rows[keep], **over}
    v = view(rows, crs_export.COPY_ISSUE)
    assert len(v["rows"]) == 3  # breach, the kept row, one query row for the other two
    query = next(c for c in comments(v) if bc.LEAD in c)
    assert rows[keep][bc.KEY][0]["field"] not in query


def test_an_engineer_worded_finding_keeps_its_own_row_end_to_end(monkeypatch):
    worded = finding(1, page=2, engineer_comment="Invented engineer words")
    rows = issue_rows(monkeypatch, [worded, *DEFERRED[1:], BREACH], True)
    v = view(rows, crs_export.COPY_ISSUE)
    assert any(c.endswith("\nInvented engineer words") for c in comments(v))
    query = next(c for c in comments(v) if bc.LEAD in c)
    assert "Invented quantity 1" not in query
    assert len(v["rows"]) == 3


def test_a_row_merged_with_another_finding_after_mapping_keeps_its_own_row(monkeypatch):
    rows = issue_rows(monkeypatch, [*DEFERRED, BREACH], True)
    keep = next(i for i, r in enumerate(rows) if bc.KEY in r)
    rows[keep] = {
        **rows[keep],
        "finding_ids": [*rows[keep]["finding_ids"], "fid-other"],
    }
    v = view(rows, crs_export.COPY_ISSUE)
    assert len(v["rows"]) == 3


def test_one_deferred_row_alone_is_left_as_it_was(monkeypatch):
    rows = issue_rows(monkeypatch, [DEFERRED[0], BREACH], True)
    v = view(rows, crs_export.COPY_ISSUE)
    assert len(v["rows"]) == 2
    assert not any(bc.LEAD in c for c in comments(v))


def test_the_closed_word_is_the_numbers_own():
    assert bc._CLOSED == crs_numbers.CLOSED


# ------------------------------------------------------------ switch off: every export path as on main


@pytest.mark.parametrize("copy", crs_export.COPIES)
@pytest.mark.parametrize("quality", [False, True])
def test_switch_off_every_export_path_is_one_row_per_field(monkeypatch, copy, quality):
    rows = issue_rows(monkeypatch, [*DEFERRED, BREACH], False)
    meta = {"review_run_id": "run-inv", "copy": copy, "export_quality": quality}
    v = crs_export.build_crs_view([dict(r) for r in rows], meta)
    assert len(v["rows"]) == 4
    assert not any(bc.LEAD in r["comment"] for r in v["rows"])


@pytest.mark.parametrize("copy", crs_export.COPIES)
@pytest.mark.parametrize("quality", [False, True])
def test_switch_off_the_workbook_ignores_the_entries(monkeypatch, copy, quality):
    """Off, a row carrying entries (built with the switch on) is drawn exactly as the same row without them,
    on both copies, quality on or off: the export half is inert."""
    marked = issue_rows(monkeypatch, [*DEFERRED, BREACH], True)
    plain = [{k: v for k, v in r.items() if k != bc.KEY} for r in marked]
    switch(monkeypatch, False)
    meta = {"review_run_id": "run-inv", "copy": copy, "export_quality": quality}
    assert cells(crs_export.build_crs(marked, dict(meta))) == cells(
        crs_export.build_crs(plain, dict(meta))
    )
    assert crs_export.build_crs_view(
        [dict(r) for r in marked], dict(meta)
    ) == crs_export.build_crs_view([dict(r) for r in plain], dict(meta))


@pytest.mark.parametrize("quality", [False, True])
def test_switch_on_the_workbook_prints_the_query_row_on_the_contractor_copy(
    monkeypatch, quality
):
    rows = issue_rows(monkeypatch, [*DEFERRED, BREACH], True)
    meta = {
        "review_run_id": "run-inv",
        "copy": crs_export.COPY_ISSUE,
        "export_quality": quality,
    }
    text = "\n".join(
        str(c)
        for sheet in cells(crs_export.build_crs(rows, meta))
        for r in sheet
        for c in r
        if c
    )
    assert text.count(bc.LEAD) == 1
    for n in (1, 2, 3):
        assert f"Invented quantity {n}" in text


def test_with_export_quality_on_a_long_query_row_keeps_every_field_in_its_comment(
    monkeypatch,
):
    """The export-quality cut (350 characters) would move the later fields to another column; the query
    row keeps them all in its own comment cell."""
    many = [finding(n, page=n) for n in range(1, 13)]
    rows = issue_rows(monkeypatch, many, True)
    meta = {
        "review_run_id": "run-inv",
        "copy": crs_export.COPY_ISSUE,
        "export_quality": True,
    }
    v = crs_export.build_crs_view([dict(r) for r in rows], meta)
    (query,) = [r for r in v["rows"] if bc.LEAD in r["comment"]]
    assert len(query["comment"]) > 350
    for n in range(1, 13):
        assert f"- Invented quantity {n} (tag Q-7, p.{n}" in query["comment"]
    assert crs_export.AI_COLUMN not in v["columns"]


# ------------------------------------------------------------ review fixes: replies, audit count, row height


def numbered(rows):
    return [
        {**r, "crs_ref": f"CRS-INV-{i:03d}", "crs_status": "Open"}
        for i, r in enumerate(rows, 1)
    ]


def test_a_reply_on_the_query_row_is_read_for_every_members_number(monkeypatch):
    from app import crs_reply

    rows = numbered(issue_rows(monkeypatch, [*DEFERRED, BREACH], True))
    members = [r["crs_ref"] for r in rows if bc.KEY in r]
    meta = {"review_run_id": "run-inv", "copy": crs_export.COPY_ISSUE}
    wb = openpyxl.load_workbook(io.BytesIO(crs_export.build_crs(rows, meta)))
    ws = wb.worksheets[0]
    (cell,) = [c for r in ws.iter_rows() for c in r if bc.LEAD in str(c.value or "")]
    assert ws.cell(cell.row, 1).value.split("\n") == members
    ws.cell(cell.row, 6).value = "Clarification needed - invented reply"
    out = io.BytesIO()
    wb.save(out)
    replies = crs_reply.read_replies(out.getvalue())
    got = {r["item"]: r["response"] for r in replies}
    for ref in members:
        assert got[ref] == "Clarification needed - invented reply"
    assert len({r["row"] for r in replies if r["item"] in members}) == 1


def test_a_reply_on_one_members_number_alone_is_read_for_that_number():
    from app import crs_reply

    assert crs_reply.numbers_in("CRS-INV-002") == ["CRS-INV-002"]
    assert crs_reply.numbers_in("CRS-INV-002\nCRS-INV-003") == [
        "CRS-INV-002",
        "CRS-INV-003",
    ]
    # a line that is no number: the cell stays one item, matched or reported as before
    assert crs_reply.numbers_in("CRS-INV-002\ninvented note") == [
        "CRS-INV-002\ninvented note"
    ]


@pytest.mark.parametrize("on", [False, True], ids=["switch_off", "switch_on"])
def test_the_audit_reconciliation_adds_up_with_the_folded_rows(monkeypatch, on):
    from app import review_audit_rows

    rows = issue_rows(monkeypatch, [*DEFERRED, BREACH], on)
    meta = {"review_run_id": "run-inv", "copy": crs_export.COPY_ISSUE}
    rec = review_audit_rows.crs_reconciliation([dict(r) for r in rows], meta)
    assert rec["adds_up"], rec["line"]
    if on:
        assert rec["removed"]["folded_by_contractor"] == 2
        assert "folded into the By Contractor row 2" in rec["line"]
    else:
        assert "folded_by_contractor" not in rec["removed"]


def test_a_query_row_of_many_fields_is_no_taller_than_excel_allows(monkeypatch):
    many = [finding(n, page=n) for n in range(1, 61)]
    rows = issue_rows(monkeypatch, many, True)
    meta = {"review_run_id": "run-inv", "copy": crs_export.COPY_ISSUE}
    ws = openpyxl.load_workbook(
        io.BytesIO(crs_export.build_crs(rows, meta))
    ).worksheets[0]
    (cell,) = [c for r in ws.iter_rows() for c in r if bc.LEAD in str(c.value or "")]
    assert ws.row_dimensions[cell.row].height == crs_export.MAX_ROW_HEIGHT == 409
