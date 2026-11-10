"""Owner order 11 Nov 2026, step 1 (#805): the safety-tick rows ("Passed by a tested rule") are not CRS
comments. Behind CRS_ROUTING_BY_HOLD_REASON_ENABLED (off), the internal workbook shows them on their own
sheet, titled "Passed by a tested rule: engineer to tick", and the CRS sheet no longer carries them. The
contractor copy never carries them (as before). Switch off: the workbook is the one main made.
Invented rows only; no model, no database."""

from __future__ import annotations

import io

import openpyxl

from app import compliance_list, crs_export
from app import crs_tick_sheet as ts
from app.config import settings
from app.crs_mapping import ROW_KIND_SAFETY_TICK

TITLE = "Passed by a tested rule: engineer to tick"


def row(n: str, kind: str = "datasheet_check", **over) -> dict:
    """One invented CRS row; `kind` is its row kind."""
    base = {
        "finding_id": f"f-{n}",
        "document_name": "Invented sheet.pdf",
        "page_section": f"p.{n} - Invented field {n}",
        "comment": f"Invented comment {n}",
        "comment_by": "AI Review",
        "standard_reference": f"INVENTED-STD 1 4.{n}",
        "row_kind": kind,
        "engineer_confirmed": True,
    }
    return {**base, **over}


def tick(n: str, **over) -> dict:
    return row(
        n,
        ROW_KIND_SAFETY_TICK,
        comment=f"ENGINEER TO TICK (safety field): invented tick {n}",
        **over,
    )


ROWS = [row("1"), tick("2"), row("3"), tick("4")]


def switch(monkeypatch, value: bool) -> None:
    monkeypatch.setattr(settings, "crs_routing_by_hold_reason_enabled", value)
    # the Compliance list reads stored findings; these tests have none
    monkeypatch.setattr(compliance_list, "for_run", lambda run_id: [])


def book(rows, copy="internal"):
    data = crs_export.build_crs(rows, {"review_run_id": "run-1", "copy": copy})
    return openpyxl.load_workbook(io.BytesIO(data))


def texts(ws) -> list[str]:
    return [str(c) for r in ws.iter_rows(values_only=True) for c in r if c is not None]


def crs_comments(wb) -> list[str]:
    """The comment cells of the CRS table (column D below the header row)."""
    ws = wb["CRS"]
    return [
        str(ws.cell(r, 4).value)
        for r in range(crs_export.COLUMN_HEADER_ROW + 1, ws.max_row + 1)
        if str(ws.cell(r, 4).value or "").startswith(
            ("Invented comment", "ENGINEER TO TICK")
        )
    ]


def test_switch_on_tick_rows_leave_the_crs_sheet_for_their_own_section(monkeypatch):
    switch(monkeypatch, True)
    wb = book(ROWS)
    assert crs_comments(wb) == ["Invented comment 1", "Invented comment 3"]
    ws = wb[ts.SHEET]
    assert ws.cell(1, 1).value == TITLE
    assert "2 rows" in str(ws.cell(2, 1).value)
    body = texts(ws)
    assert "ENGINEER TO TICK (safety field): invented tick 2" in body
    assert "ENGINEER TO TICK (safety field): invented tick 4" in body
    assert not any(t.startswith("Invented comment") for t in body)
    # the same columns as the CRS table, header row then one line per tick row
    header = [ws.cell(ts.HEADER_ROW, c).value for c in range(1, 13)]
    assert header == [
        wb["CRS"].cell(crs_export.COLUMN_HEADER_ROW, c).value for c in range(1, 13)
    ]


def test_a_tick_row_prints_the_same_cells_as_on_the_crs_sheet_with_the_switch_off(
    monkeypatch,
):
    """The tick sheet draws the CRS table's own cells: only where the row prints changes."""
    switch(monkeypatch, False)
    off = book(ROWS)["CRS"]
    on_crs = off.cell(crs_export.COLUMN_HEADER_ROW + 2, 4).value
    off_cells = [
        off.cell(crs_export.COLUMN_HEADER_ROW + 2, c).value for c in range(2, 13)
    ]
    switch(monkeypatch, True)
    ws = book(ROWS)[ts.SHEET]
    on_cells = [ws.cell(ts.HEADER_ROW + 1, c).value for c in range(2, 13)]
    assert on_crs == "ENGINEER TO TICK (safety field): invented tick 2"
    assert on_cells == off_cells


def test_switch_on_the_sheet_sits_next_to_the_crs_sheet(monkeypatch):
    switch(monkeypatch, True)
    assert book(ROWS).sheetnames[:2] == ["CRS", ts.SHEET]


def test_switch_on_every_sheet_keeps_the_views_one_numbering(monkeypatch):
    """No renumbering: a row's Item No is the one the preview gives it, on whichever sheet it prints."""
    switch(monkeypatch, True)
    wb = book(ROWS)
    first = crs_export.COLUMN_HEADER_ROW + 1
    assert [wb["CRS"].cell(first + i, 1).value for i in range(2)] == [1, 3]
    ws = wb[ts.SHEET]
    assert [ws.cell(ts.HEADER_ROW + 1 + i, 1).value for i in range(2)] == [2, 4]


def _reasoned(rows):
    """Each invented row with its own reasoning, so a misplaced Internal line is visible."""
    return [{**r, "reasoning": f"why {r['comment']}", "rule_trust": "t"} for r in rows]


def _item_to_comment(wb) -> dict:
    """Item No -> comment over the CRS sheet and the tick sheet."""
    out = {}
    ws = wb["CRS"]
    for r in range(crs_export.COLUMN_HEADER_ROW + 1, ws.max_row + 1):
        if str(ws.cell(r, 4).value or "").startswith(("Invented", "ENGINEER")):
            out[ws.cell(r, 1).value] = ws.cell(r, 4).value
    if ts.SHEET in wb.sheetnames:
        tk = wb[ts.SHEET]
        for r in range(ts.HEADER_ROW + 1, tk.max_row + 1):
            out[tk.cell(r, 1).value] = tk.cell(r, 4).value
    return out


def test_switch_on_with_export_quality_the_internal_sheet_points_at_the_same_comment(
    monkeypatch,
):
    """Review finding on #1736: every Internal line's Item No names the row whose reasoning it carries."""
    switch(monkeypatch, True)
    monkeypatch.setattr(settings, "crs_export_quality_enabled", True)
    wb = book(_reasoned(ROWS))
    comments = _item_to_comment(wb)
    inner = wb[crs_export.quality.INTERNAL_SHEET]
    lines = [
        (inner.cell(r, 1).value, inner.cell(r, 3).value)
        for r in range(2, inner.max_row + 1)
        if str(inner.cell(r, 3).value or "").startswith("why ")
    ]
    assert len(lines) == 4
    for item_no, reasoning in lines:
        assert str(reasoning).startswith(f"why {comments[item_no]}")


def test_switch_on_the_workbook_numbers_match_the_preview(monkeypatch):
    switch(monkeypatch, True)
    monkeypatch.setattr(settings, "crs_export_quality_enabled", True)
    view = crs_export.build_crs_view(
        _reasoned(ROWS), {"review_run_id": "run-1", "copy": "internal"}
    )
    preview = {r["item_no"]: r["comment"] for r in view["rows"]}
    assert _item_to_comment(book(_reasoned(ROWS))) == preview


def test_switch_on_a_permanent_number_is_kept_on_the_tick_sheet(monkeypatch):
    switch(monkeypatch, True)
    wb = book([row("1"), tick("2", crs_ref="CRS-INV-007")])
    ws = wb[ts.SHEET]
    assert ws.cell(ts.HEADER_ROW + 1, 1).value == "CRS-INV-007"


def test_switch_on_the_contractor_copy_has_no_tick_row_and_no_tick_sheet(monkeypatch):
    switch(monkeypatch, True)
    wb = book(ROWS, copy="issue")
    assert ts.SHEET not in wb.sheetnames
    assert not any("ENGINEER TO TICK" in t for ws in wb for t in texts(ws))


def test_switch_on_the_section_never_splits_a_contractor_copy(monkeypatch):
    """Defence in depth: the issue copy already drops tick rows; were one to reach it, it is not given a sheet."""
    switch(monkeypatch, True)
    view = {"crs_copy": crs_export.COPY_ISSUE, "rows": [tick("2")]}
    assert crs_export._tick_section(view) == view


def test_switch_on_no_tick_row_means_no_tick_sheet(monkeypatch):
    switch(monkeypatch, True)
    wb = book([row("1"), row("3")])
    assert ts.SHEET not in wb.sheetnames
    assert crs_comments(wb) == ["Invented comment 1", "Invented comment 3"]


def test_switch_off_the_tick_rows_stay_on_the_crs_sheet_as_on_main(monkeypatch):
    switch(monkeypatch, False)
    wb = book(ROWS)
    assert ts.SHEET not in wb.sheetnames
    assert crs_comments(wb) == [
        "Invented comment 1",
        "ENGINEER TO TICK (safety field): invented tick 2",
        "Invented comment 3",
        "ENGINEER TO TICK (safety field): invented tick 4",
    ]
    first = crs_export.COLUMN_HEADER_ROW + 1
    assert [wb["CRS"].cell(first + i, 1).value for i in range(4)] == [1, 2, 3, 4]


def test_switch_off_every_sheet_is_cell_for_cell_the_same_as_without_the_section(
    monkeypatch,
):
    """Off, the builder never reaches the section code: the workbook equals one built with the
    section helper replaced by the identity."""
    switch(monkeypatch, False)
    off = book(ROWS)
    monkeypatch.setattr(crs_export, "_tick_section", lambda view: view)
    plain = book(ROWS)
    assert off.sheetnames == plain.sheetnames
    for a, b in zip(off, plain, strict=True):
        assert list(a.iter_rows(values_only=True)) == list(
            b.iter_rows(values_only=True)
        )


def test_the_screen_preview_still_carries_the_tick_rows(monkeypatch):
    """Which sheet a row prints on is the workbook's choice: the preview (where the tick is made) keeps them."""
    switch(monkeypatch, True)
    view = crs_export.build_crs_view(
        ROWS, {"review_run_id": "run-1", "copy": "internal"}
    )
    assert [r["row_kind"] for r in view["rows"]].count(ROW_KIND_SAFETY_TICK) == 2
