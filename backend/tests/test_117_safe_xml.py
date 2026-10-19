"""Order 117 item 8: uploaded office files are parsed with defusedxml.

An entity bomb (billion laughs) or an external entity (XXE) in a part of a
contractor's .xlsx is refused by the workbook preview and by the merged-cell
reader, and openpyxl itself runs in its defusedxml mode. Invented XML only.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from app import datasheet_inputs, workbook

BOMB = (
    b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
    b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
    b'<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">]>'
    b"<worksheet>&lol3;</worksheet>"
)
XXE = (
    b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/hostname">]>'
    b"<worksheet>&e;</worksheet>"
)


@pytest.mark.parametrize("payload", [BOMB, XXE], ids=["billion-laughs", "xxe"])
def test_the_workbook_preview_refuses_a_part_that_declares_entities(payload):
    with pytest.raises(workbook.WorkbookError, match="refused XML"):
        workbook._parse(payload)


def test_a_plain_part_still_parses():
    assert workbook._parse(b"<worksheet><sheetData/></worksheet>").tag == "worksheet"


@pytest.mark.parametrize("payload", [BOMB, XXE], ids=["billion-laughs", "xxe"])
def test_the_merged_cell_reader_reads_nothing_from_a_hostile_sheet(payload):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/worksheets/sheet1.xml", payload)
    with zipfile.ZipFile(buf) as zf:
        assert datasheet_inputs._merged_ranges(zf, "xl/worksheets/sheet1.xml") == []


def test_openpyxl_runs_in_its_defusedxml_mode():
    from openpyxl.xml import DEFUSEDXML

    assert DEFUSEDXML is True
