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


def test_a_docx_part_is_refused_by_defusedxml_even_past_the_doctype_check(monkeypatch):
    """Order 133: the docx reader's DOCTYPE regex is no longer the only guard."""
    import re

    from defusedxml import DefusedXmlException

    monkeypatch.setattr(datasheet_inputs, "_DOCTYPE", re.compile(rb"(?!)"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", BOMB)
    with zipfile.ZipFile(buf) as zf:
        with pytest.raises(DefusedXmlException):
            datasheet_inputs._parse_bounded(zf, "word/document.xml")


def test_no_code_parses_xml_with_the_standard_library_parser():
    """Order 133: every XML parse in the app, scripts and eval goes through
    defusedxml. `ET` / `etree` name the standard library here; a file may
    call `ElementTree.` only when that name is defusedxml's."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    call = re.compile(r"\b(ET|ElementTree|etree)\.(fromstring|parse|iterparse|XML)\(")
    found = []
    for folder in ("backend/app", "scripts", "eval"):
        for path in sorted((root / folder).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            safe = "from defusedxml import ElementTree\n" in text
            for m in call.finditer(text):
                if m.group(1) == "ElementTree" and safe:
                    continue
                found.append(f"{path.relative_to(root).as_posix()}: {m.group(0)}")
    assert found == []
