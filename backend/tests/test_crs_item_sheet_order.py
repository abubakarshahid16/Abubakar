"""#1592 item c: on the internal copy, Item No is the sheet order, 001 up; the permanent
number stays what a contractor quotes back and what a reply is matched by, and every route
still keys on it. Invented rows only; the routes are `test_review_screen`'s synthetic world.
"""

from __future__ import annotations

import io

import openpyxl
from fastapi.testclient import TestClient

from app import access, crs_export, crs_numbers
from app.config import settings
from app.main import _crs_content, app
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_crs_permanent_numbers import _confirm
from tests.test_review_screen import _noise_rows, world  # noqa: F401

ON = {"review_run_id": "run-1", "export_quality": True}
#: Jumping numbers, as a run's rows carry them: a number is never reused.
NUMBERS = ("CRS-INV-1-002", "CRS-INV-1-110", "CRS-INV-1-039")


def _rows():
    return [
        {
            "document_name": "invented.pdf",
            "page_section": f"p.{n} - Invented field {n}",
            "comment": f"Invented comment {n}.",
            "comment_by": "AI Review",
            "standard_reference": f"INV {n}",
            "row_kind": "datasheet_check",
            "engineer_confirmed": True,
            "crs_ref": ref,
            "crs_status": "Open",
            "priority": 3,
            "reasoning": "" if n == 1 else "Read: invented.",
            "rule_trust": "",
        }
        for n, ref in enumerate(NUMBERS, start=1)
    ]


def _view(copy="internal", **meta):
    return crs_export.build_crs_view(_rows(), {**ON, "copy": copy, **meta})


def test_the_internal_copy_numbers_rows_in_sheet_order(monkeypatch):
    monkeypatch.setattr(settings, "crs_item_sheet_order_enabled", True)
    rows = _view()["rows"]
    assert [r["item_no"] for r in rows] == ["001", "002", "003"]
    assert [r["crs_ref"] for r in rows] == list(NUMBERS), "every route keys on this"


def test_the_workbook_prints_the_sheet_order_and_the_internal_sheet_the_number(
    monkeypatch,
):
    monkeypatch.setattr(settings, "crs_item_sheet_order_enabled", True)
    data = crs_export.build_crs(_rows(), {**ON, "copy": "internal"})
    book = openpyxl.load_workbook(io.BytesIO(data))
    first = crs_export.COLUMN_HEADER_ROW + 1
    assert [book["CRS"].cell(first + i, 1).value for i in range(3)] == [
        "001",
        "002",
        "003",
    ]
    inner = list(book["Internal"].iter_rows(values_only=True))
    assert inner[0][:5] == (
        "Item No",
        "Row ref",
        "Reasoning (internal)",
        "Rule trust (internal)",
        "Permanent number",
    )
    # every numbered row is listed, the one with no reasoning too
    assert {r[0]: r[4] for r in inner[1:4]} == dict(
        zip(("001", "002", "003"), NUMBERS, strict=True)
    )
    notes = list(book["Review notes"].iter_rows(values_only=True))
    said = next(r for r in notes if r[0] == "Item numbers")
    assert said[2] == 3 and "permanent number" in said[3]


def test_the_issue_copy_keeps_the_permanent_number(monkeypatch):
    """A contractor quotes it back, and it is all a reply is matched by."""
    monkeypatch.setattr(settings, "crs_item_sheet_order_enabled", True)
    assert [r["item_no"] for r in _view("issue")["rows"]] == list(NUMBERS)


def test_switch_off_the_item_no_and_the_internal_sheet_are_as_before():
    assert settings.crs_item_sheet_order_enabled is False
    rows = _view()["rows"]
    assert [r["item_no"] for r in rows] == list(NUMBERS)
    data = crs_export.build_crs(_rows(), {**ON, "copy": "internal"})
    book = openpyxl.load_workbook(io.BytesIO(data))
    inner = list(book["Internal"].iter_rows(values_only=True))
    assert inner[0][:4] == (
        "Item No",
        "Row ref",
        "Reasoning (internal)",
        "Rule trust (internal)",
    )
    assert inner[0][4:] == () or not any(inner[0][4:])
    # as before: a row with no reasoning is not on that sheet
    assert [r[0] for r in inner[1:3]] == list(NUMBERS[1:])
    assert not any(
        r[0] == "Item numbers" for r in book["Review notes"].iter_rows(values_only=True)
    )


def test_without_the_quality_export_there_is_no_internal_sheet_so_the_number_stays(
    monkeypatch,
):
    monkeypatch.setattr(settings, "crs_item_sheet_order_enabled", True)
    assert [r["item_no"] for r in _view(export_quality=False)["rows"]] == list(NUMBERS)


def test_a_row_with_no_number_still_gets_its_position(monkeypatch):
    rows = [{**_rows()[0], "crs_ref": ""}]
    meta = {**ON, "copy": "internal"}
    assert crs_export.build_crs_view(rows, meta)["rows"][0]["item_no"] == 1
    monkeypatch.setattr(settings, "crs_item_sheet_order_enabled", True)
    assert crs_export.build_crs_view(rows, meta)["rows"][0]["item_no"] == "001"


def test_a_position_can_never_be_read_as_a_permanent_number():
    assert crs_numbers.parse_ref("001") is None
    assert crs_numbers.parse_ref("068") is None


def test_the_reply_import_status_and_history_still_key_on_the_number(
    world,  # noqa: F811 - the fixture imported above
    monkeypatch,
):
    """The round trip, end to end, with the switch on: the issue copy's number is matched;
    a sheet-order number on an internal copy is counted, never attached by position."""
    _sub, run, scope = world
    _confirm(run, scope, monkeypatch)
    monkeypatch.setattr(settings, "crs_export_quality_enabled", True)
    monkeypatch.setattr(settings, "crs_item_sheet_order_enabled", True)
    client = TestClient(app)
    [row] = _noise_rows(run)
    ref = row["crs_ref"]
    assert crs_numbers.parse_ref(ref) is not None
    assert row["item_no"] != ref and crs_numbers.parse_ref(str(row["item_no"])) is None

    # a reply typed on the internal copy: the number there is a position
    internal = client.get(f"/api/reviews/runs/{run}/crs").content
    book = openpyxl.load_workbook(io.BytesIO(internal))
    sheet = book["CRS"]
    first = crs_export.COLUMN_HEADER_ROW + 1
    assert all(
        crs_numbers.parse_ref(str(sheet.cell(first + i, 1).value)) is None
        for i in range(2)
    )
    sheet.cell(first, 6).value = "Accepted"
    buffer = io.BytesIO()
    book.save(buffer)
    body = client.post(
        f"/api/reviews/runs/{run}/crs/reply",
        files={"file": ("reply.xlsx", buffer.getvalue(), "application/octet-stream")},
    ).json()
    assert body["updated"] == 0
    assert body["not_a_crs_number"] >= 1
    [row] = _noise_rows(run)
    assert row["contractor_response"] == ""

    # the issue copy keeps the permanent number, and the same reply is matched by it
    rows, meta, _name, _stamp = _crs_content(
        run, access.AccessScope(user_id="t", allowed_document_ids=scope), "issue"
    )
    book = openpyxl.load_workbook(io.BytesIO(crs_export.build_crs(rows, meta)))
    sheet = book.active
    assert sheet.cell(first, 1).value == ref
    sheet.cell(first, 6).value = "Accepted"
    buffer = io.BytesIO()
    book.save(buffer)
    body = client.post(
        f"/api/reviews/runs/{run}/crs/reply",
        files={"file": ("reply.xlsx", buffer.getvalue(), "application/octet-stream")},
    ).json()
    assert body["updated"] == 1
    assert (
        client.get(f"/api/reviews/runs/{run}/crs/comments/{ref}/history").status_code
        == 200
    )
    [row] = _noise_rows(run)
    assert row["contractor_response"].startswith("Accepted")
