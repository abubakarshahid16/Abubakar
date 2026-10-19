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


def _docx_part(payload: bytes):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", payload)
    return zipfile.ZipFile(buf)


def test_a_docx_part_is_refused_by_defusedxml_even_past_the_doctype_check(monkeypatch):
    """Order 133: the docx reader's DOCTYPE regex is no longer the only guard,
    and defusedxml's refusal reads as a DOCTYPE, not as a damaged file."""
    import re

    monkeypatch.setattr(datasheet_inputs, "_DOCTYPE", re.compile(rb"(?!)"))
    with _docx_part(BOMB) as zf, pytest.raises(datasheet_inputs.InputError) as err:
        datasheet_inputs._parse_bounded(zf, "word/document.xml")
    assert err.value.code == "doctype"


def test_a_utf16_docx_part_with_a_doctype_is_refused_as_a_doctype():
    """The byte regex cannot see a UTF-16 DOCTYPE; defusedxml can."""
    payload = BOMB.replace(b'<?xml version="1.0"?>', b"").decode().encode("utf-16")
    assert not datasheet_inputs._DOCTYPE.search(payload)
    with _docx_part(payload) as zf, pytest.raises(datasheet_inputs.InputError) as err:
        datasheet_inputs._parse_bounded(zf, "word/document.xml")
    assert err.value.code == "doctype"


_PARSE_NAMES = {"fromstring", "parse", "iterparse", "XML", "parseString", "XMLParser"}


def _stdlib_xml_parse_calls(source: str) -> list[str]:
    """Calls into the standard library's XML parsers, however they were
    imported (`import xml.etree.ElementTree as X`, `from xml.dom.minidom
    import parseString`, ...). defusedxml's modules are not `xml.*`."""
    import ast

    tree = ast.parse(source)
    modules, functions = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] == "xml":
                    modules.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("xml"):
            for a in node.names:
                if a.name in _PARSE_NAMES:
                    functions.add(a.asname or a.name)
                else:
                    modules.add(a.asname or a.name)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id in functions:
            found.append(f"{f.id}( line {node.lineno}")
        elif isinstance(f, ast.Attribute) and f.attr in _PARSE_NAMES:
            root = f.value
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and root.id in modules:
                found.append(f"{root.id}...{f.attr}( line {node.lineno}")
    return found


def test_the_scan_sees_aliased_and_bare_imports():
    """Not vacuous: the forms a regex scan missed are caught."""
    assert _stdlib_xml_parse_calls(
        "import xml.etree.ElementTree as X\nX.fromstring(b)\n"
    )
    assert _stdlib_xml_parse_calls(
        "from xml.etree.ElementTree import fromstring\nfromstring(b)\n"
    )
    assert _stdlib_xml_parse_calls(
        "from xml.dom import minidom\nminidom.parseString(b)\n"
    )
    assert _stdlib_xml_parse_calls(
        "from xml.etree import ElementTree as ET\nET.parse(f)\n"
    )
    assert not _stdlib_xml_parse_calls(
        "from xml.etree import ElementTree as ET\n"
        "from defusedxml import ElementTree as SafeET\n"
        "SafeET.fromstring(b)\nET.ParseError\n"
    )


def test_no_code_parses_xml_with_the_standard_library_parser():
    """Order 133: every XML parse in the app, scripts and eval goes through
    defusedxml; the standard library's module may name types and errors only."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    found = []
    for folder in ("backend/app", "scripts", "eval"):
        for path in sorted((root / folder).rglob("*.py")):
            for hit in _stdlib_xml_parse_calls(path.read_text(encoding="utf-8")):
                found.append(f"{path.relative_to(root).as_posix()}: {hit}")
    assert found == []
