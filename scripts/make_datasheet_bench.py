"""Write the made-up datasheet benchmark: 14 files and their answer key.

    python scripts/make_datasheet_bench.py

EVERYTHING HERE IS MADE UP. No field, value, tag, number or name comes from
a real document; tags and document numbers use the fixture prefixes (SYN-,
DS-) and the 0000/0001/1234/9999 numbers. The files land in
`backend/tests/fixtures/synthetic/datasheets/`, the one path the CI guard
allows binaries in, and are committed so every reader is measured on the
same bytes.

WHY FOURTEEN DIFFERENT LAYOUTS. A reader tuned on one sheet shape reads that
shape. The set spans the shapes contractor datasheets actually come in -
ruled tables, unruled "Label : value" lines, two-column forms, Required /
Offered columns, grids with a Units column, grids with unusual header words,
answers written as sentences, merged cells, a rotated page, a multi-page
sheet with a repeated title block, an image-only scan, a spreadsheet and a
Word table - and one sheet whose "By Vendor" and empty cells must NOT be
reported as values.

THE ANSWER KEY IS WRITTEN FROM THE SAME ROWS THAT ARE DRAWN, so a value can
never be in the key and missing from the page by a typing slip. Per file:

  expected  - {field, value, unit, kind[, aliases][, column]} a correct reader
              must find. `kind` is claude_datasheet's vocabulary (required /
              offered / measured); `aliases` are other names the SAME printed
              row is fairly read as (a sub-label under a merged group cell);
              `column` is informational.
  forbidden - fields printed with no value ("By Vendor", "TBA", an empty
              cell). Reporting a VALUE for one is an error; recording it as a
              blank is not.
  ignore    - title-block fields (document number, tag, revision): not
              equipment facts, not scored either way.

DETERMINISTIC: fixed metadata, no new PDF /ID, fixed zip timestamps - the same
bytes on every run (checked by running twice and comparing hashes).
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

import pymupdf

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "backend" / "tests" / "fixtures" / "synthetic" / "datasheets"

A4 = (595, 842)
FONT = 9
#: The zip timestamp every archive member gets (the zip format's own epoch).
ZIP_TIME = (1980, 1, 1, 0, 0, 0)

KEY: dict[str, dict] = {}

TITLE_IGNORE = ["Doc No", "Tag No", "Rev", "Project", "Sheet"]


# ------------------------------------------------------------------ helpers

def row(field, value, unit=None, kind="offered", **extra):
    """One expected answer. `value` is printed as written; `unit` beside it."""
    return {"field": field, "value": str(value), "unit": unit, "kind": kind, **extra}


def printed(r: dict) -> str:
    return f"{r['value']} {r['unit']}" if r.get("unit") else r["value"]


def record(name, *, equipment, layout, expected, forbidden=(), ignore=TITLE_IGNORE,
           text_layer=True):
    KEY[name] = {"equipment": equipment, "layout": layout, "text_layer": text_layer,
                 "expected": expected, "forbidden": list(forbidden), "ignore": list(ignore)}


def title_block(page, doc_no, tag, title, *, y=40):
    page.insert_text((40, y), title, fontsize=12, fontname="hebo")
    page.insert_text((40, y + 18), f"Doc No.: {doc_no}", fontsize=FONT)
    page.insert_text((220, y + 18), f"Tag No.: {tag}", fontsize=FONT)
    page.insert_text((400, y + 18), "Rev: 0", fontsize=FONT)
    page.insert_text((40, y + 32), "Project: Synthetic Plant 0001", fontsize=FONT)


def save_pdf(doc: pymupdf.Document, name: str) -> None:
    doc.set_metadata({})
    doc.save(str(OUT / name), garbage=4, deflate=True, no_new_id=True)
    doc.close()


def ruled_table(page, top, widths, rows, *, height=18, left=40, fontsize=FONT):
    """Every cell ruled; `rows` are lists of cell strings (None = no text)."""
    y = top
    for cells in rows:
        x = left
        for width, cell in zip(widths, cells):
            page.draw_rect(pymupdf.Rect(x, y, x + width, y + height), color=(0, 0, 0), width=0.6)
            if cell:
                page.insert_text((x + 4, y + height - 5), str(cell), fontsize=fontsize)
            x += width
        y += height
    return y


def normalised_zip(raw: bytes) -> bytes:
    """Rewrite a zip with fixed member timestamps and fixed core-property dates."""
    src = zipfile.ZipFile(io.BytesIO(raw))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "docProps/core.xml":
                data = re.sub(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*",
                              rb"\g<1>2026-01-01T00:00:00Z", data)
            member = zipfile.ZipInfo(info.filename, date_time=ZIP_TIME)
            member.compress_type = zipfile.ZIP_DEFLATED
            member.external_attr = 0o644 << 16
            member.create_system = 3   # ZipInfo stamps the host OS (0 on Windows); pin it
            dst.writestr(member, data)
    return out.getvalue()


# ------------------------------------------------------------- the sheets

def ds01_pump_ruled():
    name = "ds01_pump_ruled.pdf"
    rows = [row("Rated capacity", "125", "m3/h"), row("Differential head", "85", "m"),
            row("Suction pressure", "1.5", "barg"), row("Discharge pressure", "9.8", "barg"),
            row("Pumping temperature", "45", "°C"), row("Speed", "2950", "rpm"),
            row("Driver power", "55", "kW"), row("Impeller diameter", "310", "mm"),
            row("NPSH required", "3.2", "m"), row("Casing material", "Carbon steel")]
    doc = pymupdf.open(); page = doc.new_page(width=A4[0], height=A4[1])
    title_block(page, "DS-0001-P", "SYN-P-0001", "CENTRIFUGAL PUMP DATASHEET")
    body = [[r["field"], printed(r)] for r in rows] + [["Coupling type", "By Vendor"]]
    ruled_table(page, 110, [240, 240], body)
    save_pdf(doc, name)
    record(name, equipment="centrifugal pump", layout="ruled two-column table",
           expected=rows, forbidden=["Coupling type"])


def ds02_psv_unruled():
    name = "ds02_psv_unruled.pdf"
    rows = [row("Set pressure", "12.5", "barg"), row("Relieving temperature", "180", "°C"),
            row("Required capacity", "5400", "kg/h"), row("Inlet size", "3", "in"),
            row("Outlet size", "4", "in"), row("Back pressure", "1.2", "barg"),
            row("Overpressure", "10", "%"), row("Orifice designation", "J"),
            row("Body material", "Carbon steel"), row("Valve type", "Conventional spring loaded")]
    doc = pymupdf.open(); page = doc.new_page(width=A4[0], height=A4[1])
    title_block(page, "DS-0002-V", "SYN-PSV-0001", "PRESSURE SAFETY VALVE DATASHEET")
    y = 120
    for r in rows:
        page.insert_text((50, y), f"{r['field']} : {printed(r)}", fontsize=FONT)
        y += 16
    page.insert_text((50, y), "Bellows material :", fontsize=FONT)
    save_pdf(doc, name)
    record(name, equipment="pressure safety valve", layout="unruled 'Label : value' lines",
           expected=rows, forbidden=["Bellows material"])


def ds03_hx_two_column_form():
    name = "ds03_hx_two_column_form.pdf"
    left = [row("Heat duty", "2.45", "MW"), row("Shell design pressure", "16", "barg"),
            row("Shell design temperature", "250", "°C"), row("Surface area", "185", "m2"),
            row("Tube OD", "19.05", "mm"), row("Corrosion allowance", "3", "mm")]
    right = [row("TEMA type", "AES"), row("Tube design pressure", "25", "barg"),
             row("Tube design temperature", "200", "°C"), row("Number of passes", "2"),
             row("Tube length", "6100", "mm"), row("Baffle cut", "25", "%")]
    doc = pymupdf.open(); page = doc.new_page(width=A4[0], height=A4[1])
    title_block(page, "DS-0003-E", "SYN-E-0001", "SHELL AND TUBE HEAT EXCHANGER")
    page.draw_rect(pymupdf.Rect(36, 104, 559, 104 + 22 * len(left) + 8), color=(0, 0, 0), width=0.8)
    y = 122
    for a, b in zip(left, right):
        page.insert_text((42, y), a["field"], fontsize=FONT)
        page.insert_text((180, y), printed(a), fontsize=FONT)
        page.insert_text((310, y), b["field"], fontsize=FONT)
        page.insert_text((460, y), printed(b), fontsize=FONT)
        y += 22
    save_pdf(doc, name)
    record(name, equipment="shell and tube heat exchanger",
           layout="two-column form (two label/value pairs per line, unruled inside a frame)",
           expected=left + right)


def ds04_control_valve_req_off():
    name = "ds04_control_valve_req_off.pdf"
    pairs = [("Maximum flow", ("150", "m3/h"), ("150", "m3/h")),
             ("Valve Cv", ("180", None), ("210", None)),
             ("Body size", ("6", "in"), ("6", "in")),
             ("Shutoff pressure", ("20", "barg"), ("25", "barg")),
             ("Noise level", ("85", "dBA"), ("82", "dBA")),
             ("Stroke time", ("10", "s"), ("8", "s")),
             ("Leakage class", ("Class IV", None), ("Class V", None))]
    expected = []
    body = [["Description", "Required", "Offered"]]
    for field, req, off in pairs:
        r = row(field, req[0], req[1], kind="required")
        o = row(field, off[0], off[1], kind="offered")
        expected += [r, o]
        body.append([field, printed(r), printed(o)])
    body.append(["Actuator air supply", "5.5 barg", "By Vendor"])
    expected.append(row("Actuator air supply", "5.5", "barg", kind="required"))
    doc = pymupdf.open(); page = doc.new_page(width=A4[0], height=A4[1])
    title_block(page, "DS-0004-FV", "SYN-FV-0001", "CONTROL VALVE DATASHEET")
    ruled_table(page, 110, [200, 140, 140], body)
    save_pdf(doc, name)
    record(name, equipment="control valve", layout="ruled table with Required / Offered columns",
           expected=expected)


def ds05_motor_units_grid():
    name = "ds05_motor_units_grid.pdf"
    rows = [row("Rated power", "75", "kW"), row("Rated voltage", "400", "V"),
            row("Frequency", "50", "Hz"), row("Speed", "1485", "rpm"),
            row("Full load current", "132", "A"), row("Efficiency", "95.2", "%"),
            row("Power factor", "0.87"), row("Weight", "520", "kg"),
            row("Insulation class", "F"), row("Enclosure", "IP55")]
    body = [["Parameter", "Units", "Value"]] + [
        [r["field"], r["unit"] or "-", r["value"]] for r in rows]
    doc = pymupdf.open(); page = doc.new_page(width=A4[0], height=A4[1])
    title_block(page, "DS-0005-M", "SYN-PM-0001", "LV INDUCTION MOTOR DATASHEET")
    ruled_table(page, 110, [220, 90, 150], body)
    save_pdf(doc, name)
    record(name, equipment="electric motor", layout="ruled grid with a Units column",
           expected=rows)


def ds06_transmitter_odd_headers():
    name = "ds06_transmitter_odd_headers.pdf"
    rows = [row("Range lower limit", "0", "bar"), row("Range upper limit", "40", "bar"),
            row("Accuracy", "0.075", "%"), row("Supply voltage", "24", "V"),
            row("Maximum ambient temperature", "85", "°C"), row("Response time", "100", "ms"),
            row("Communication protocol", "HART"), row("Wetted parts material", "316L SS")]
    body = [["Attribute", "Measure", "Figure"]] + [
        [r["field"], r["unit"] or "", r["value"]] for r in rows]
    doc = pymupdf.open(); page = doc.new_page(width=A4[0], height=A4[1])
    title_block(page, "DS-0006-PT", "SYN-PT-0001", "PRESSURE TRANSMITTER DATASHEET")
    ruled_table(page, 110, [220, 90, 150], body)
    save_pdf(doc, name)
    record(name, equipment="pressure transmitter",
           layout="ruled grid with unusual header words (Attribute / Measure / Figure)",
           expected=rows)


def ds07_gate_valve_free_text():
    name = "ds07_gate_valve_free_text.pdf"
    lines = [
        ("Nominal size: 6 in, full bore.", row("Nominal size", "6", "in")),
        ("Pressure class: ASME Class 600.", row("Pressure class", "Class 600")),
        ("Body material: forged carbon steel to ASTM A105.",
         row("Body material", "forged carbon steel to ASTM A105")),
        ("Trim material: thirteen percent chromium stainless steel.",
         row("Trim material", "thirteen percent chromium stainless steel")),
        ("The hydrostatic shell test pressure is 153 barg, held for 5 minutes.",
         row("Hydrostatic shell test pressure", "153", "barg", kind="measured")),
        ("Face to face dimension of 787 mm per the purchaser's specification.",
         row("Face to face dimension", "787", "mm")),
        ("Delivery: 16 weeks from purchase order, ex works.", row("Delivery", "16", "weeks")),
        ("Warranty: 18 months from delivery or 12 months from start-up.",
         row("Warranty", "18", "months")),
        ("Operator: handwheel with bevel gearbox.", row("Operator", "handwheel with bevel gearbox")),
    ]
    doc = pymupdf.open(); page = doc.new_page(width=A4[0], height=A4[1])
    title_block(page, "DS-0007-GV", "SYN-GV-0001", "GATE VALVE - VENDOR TECHNICAL OFFER")
    page.insert_text((40, 110), "Vendor answers to the purchaser's questions:", fontsize=FONT)
    y = 132
    for number, (text, _) in enumerate(lines, start=1):
        page.insert_text((40, y), f"{number}. {text}", fontsize=FONT)
        y += 18
    save_pdf(doc, name)
    record(name, equipment="gate valve",
           layout="free-text answers (values written inside sentences, vendor terms)",
           # The warranty sentence states TWO values under two conditions, so
           # a reader that reports both has read the page correctly.
           expected=[r for _, r in lines] + [row("Warranty", "12", "months")])


def ds08_tank_merged_cells():
    name = "ds08_tank_merged_cells.pdf"
    doc = pymupdf.open(); page = doc.new_page(width=A4[0], height=A4[1])
    title_block(page, "DS-0008-T", "SYN-T-0001", "ATMOSPHERIC STORAGE TANK DATASHEET")
    left, top, h = 40, 110, 18
    widths = [120, 160, 200]
    # Group cells merged over two rows each: DESIGN (pressure, temperature)
    # and GEOMETRY (diameter, height); the sub-label names the field.
    groups = [("DESIGN", [("Pressure", "0.05 barg"), ("Temperature", "85 °C")]),
              ("GEOMETRY", [("Diameter", "12000 mm"), ("Height", "14500 mm")])]
    y = top
    for group, subs in groups:
        page.draw_rect(pymupdf.Rect(left, y, left + widths[0], y + h * len(subs)), color=(0, 0, 0), width=0.6)
        page.insert_text((left + 4, y + h * len(subs) / 2 + 3), group, fontsize=FONT)
        for label, value in subs:
            page.draw_rect(pymupdf.Rect(left + widths[0], y, left + widths[0] + widths[1], y + h), color=(0, 0, 0), width=0.6)
            page.draw_rect(pymupdf.Rect(left + widths[0] + widths[1], y, left + sum(widths), y + h), color=(0, 0, 0), width=0.6)
            page.insert_text((left + widths[0] + 4, y + h - 5), label, fontsize=FONT)
            page.insert_text((left + widths[0] + widths[1] + 4, y + h - 5), value, fontsize=FONT)
            y += h
    # Label cells merged across the first two columns.
    for label, value in [("Nominal capacity", "1500 m3"), ("Corrosion allowance", "3 mm"),
                         ("Roof type", "Fixed cone roof"), ("Design code", "API 650")]:
        page.draw_rect(pymupdf.Rect(left, y, left + widths[0] + widths[1], y + h), color=(0, 0, 0), width=0.6)
        page.draw_rect(pymupdf.Rect(left + widths[0] + widths[1], y, left + sum(widths), y + h), color=(0, 0, 0), width=0.6)
        page.insert_text((left + 4, y + h - 5), label, fontsize=FONT)
        page.insert_text((left + widths[0] + widths[1] + 4, y + h - 5), value, fontsize=FONT)
        y += h
    # A value cell split in two: shell plate thickness, bottom and top course.
    page.draw_rect(pymupdf.Rect(left, y, left + widths[0] + widths[1], y + 2 * h), color=(0, 0, 0), width=0.6)
    page.insert_text((left + 4, y + h + 3), "Shell plate thickness", fontsize=FONT)
    for k, (label, value) in enumerate([("Bottom course", "14 mm"), ("Top course", "8 mm")]):
        yy = y + k * h
        page.draw_rect(pymupdf.Rect(left + widths[0] + widths[1], yy, left + sum(widths), yy + h), color=(0, 0, 0), width=0.6)
        page.insert_text((left + widths[0] + widths[1] + 4, yy + h - 5), f"{label}: {value}", fontsize=FONT)
    save_pdf(doc, name)
    expected = [
        row("Design pressure", "0.05", "barg", aliases=["Pressure"]),
        row("Design temperature", "85", "°C", aliases=["Temperature"]),
        row("Diameter", "12000", "mm", aliases=["Geometry diameter"]),
        row("Height", "14500", "mm", aliases=["Geometry height"]),
        row("Nominal capacity", "1500", "m3"), row("Corrosion allowance", "3", "mm"),
        row("Roof type", "Fixed cone roof"), row("Design code", "API 650"),
        row("Shell plate thickness bottom course", "14", "mm", aliases=["Bottom course"]),
        row("Shell plate thickness top course", "8", "mm", aliases=["Top course"]),
    ]
    record(name, equipment="storage tank",
           layout="ruled table with merged group cells, merged label cells and a split value cell",
           expected=expected)


def ds09_rotated_page():
    name = "ds09_rotated_page.pdf"
    rows = [row("Design pressure", "19", "barg"), row("Design temperature", "120", "°C"),
            row("Flow rate", "60", "m3/h"), row("Filtration rating", "25", "micron"),
            row("Clean pressure drop", "0.2", "bar"), row("Connection size", "4", "in"),
            row("Element material", "Stainless steel 316")]
    doc = pymupdf.open(); page = doc.new_page(width=A4[0], height=A4[1])
    title_block(page, "DS-0009-F", "SYN-F-0001", "BASKET STRAINER DATASHEET")
    ruled_table(page, 110, [240, 200], [[r["field"], printed(r)] for r in rows])
    page.set_rotation(90)
    save_pdf(doc, name)
    record(name, equipment="basket strainer", layout="ruled table on a page rotated 90 degrees",
           expected=rows)


def ds10_compressor_multipage():
    name = "ds10_compressor_multipage.pdf"
    doc = pymupdf.open()
    grid = [("Inlet flow", "Nm3/h", ("8000", "9500", "11000")),
            ("Suction pressure", "barg", ("2.0", "2.5", "2.8")),
            ("Discharge pressure", "barg", ("18.0", "19.0", "19.5")),
            ("Suction temperature", "°C", ("30", "35", "40"))]
    expected = []
    # Page 1: an API-style operating grid (Units | Minimum | Normal | Rated).
    page = doc.new_page(width=A4[0], height=A4[1])
    title_block(page, "DS-0010-K", "SYN-K-0001", "CENTRIFUGAL COMPRESSOR DATASHEET")
    page.insert_text((40, 102), "Sheet 1 of 3", fontsize=FONT)
    page.insert_text((40, 124), "OPERATING CONDITIONS", fontsize=FONT, fontname="hebo")
    cols = [("Units", 230), ("Minimum", 310), ("Normal", 390), ("Rated", 470)]
    for word, x in cols:
        page.insert_text((x, 142), word, fontsize=FONT)
    y = 160
    for label, unit, values in grid:
        page.insert_text((40, y), label, fontsize=FONT)
        page.insert_text((230, y), unit, fontsize=FONT)
        for (column, x), value in zip(cols[1:], values):
            page.insert_text((x, y), value, fontsize=FONT)
            expected.append(row(label, value, unit, column=column))
        y += 16
    # Page 2: construction, ruled.
    construction = [row("Number of stages", "2"), row("Impeller diameter", "540", "mm"),
                    row("Maximum continuous speed", "11200", "rpm"),
                    row("Driver rated power", "2400", "kW"), row("Casing split", "Horizontal")]
    page = doc.new_page(width=A4[0], height=A4[1])
    title_block(page, "DS-0010-K", "SYN-K-0001", "CENTRIFUGAL COMPRESSOR DATASHEET")
    page.insert_text((40, 102), "Sheet 2 of 3", fontsize=FONT)
    ruled_table(page, 120, [240, 200], [[r["field"], printed(r)] for r in construction])
    expected += construction
    # Page 3: utilities, with a By Vendor row.
    utilities = [row("Lube oil cooling water flow", "12", "m3/h"), row("Noise level", "85", "dBA")]
    page = doc.new_page(width=A4[0], height=A4[1])
    title_block(page, "DS-0010-K", "SYN-K-0001", "CENTRIFUGAL COMPRESSOR DATASHEET")
    page.insert_text((40, 102), "Sheet 3 of 3", fontsize=FONT)
    ruled_table(page, 120, [240, 200], [[r["field"], printed(r)] for r in utilities]
                + [["Seal gas consumption", "By Vendor"]])
    expected += utilities
    save_pdf(doc, name)
    record(name, equipment="centrifugal compressor",
           layout="three pages: an unruled Units/Minimum/Normal/Rated grid, ruled tables, a title block repeated on every page",
           expected=expected, forbidden=["Seal gas consumption"])


def ds11_flowmeter_scanned():
    name = "ds11_flowmeter_scanned.pdf"
    rows = [row("Line size", "3", "in"), row("Maximum flow", "45", "m3/h"),
            row("Accuracy", "0.1", "%"), row("Design pressure", "40", "barg"),
            row("Design temperature", "150", "°C"), row("Power supply", "24", "V"),
            row("Meter type", "Coriolis")]
    src = pymupdf.open(); page = src.new_page(width=A4[0], height=A4[1])
    title_block(page, "DS-0011-FT", "SYN-FT-0001", "CORIOLIS FLOW METER DATASHEET")
    ruled_table(page, 110, [240, 200], [[r["field"], printed(r)] for r in rows])
    png = page.get_pixmap(dpi=110, colorspace=pymupdf.csGRAY).tobytes("png")
    src.close()
    doc = pymupdf.open(); page = doc.new_page(width=A4[0], height=A4[1])
    page.insert_image(page.rect, stream=png)
    save_pdf(doc, name)
    record(name, equipment="flow meter",
           layout="image-only scanned page (no text layer)", expected=rows, text_layer=False)


def ds12_pump_xlsx():
    import datetime

    import openpyxl
    name = "ds12_pump.xlsx"
    rows = [row("Capacity", "42", "m3/h"), row("Head", "60", "m"),
            row("Speed", "2900", "rpm"), row("Motor power", "15", "kW"),
            row("Suction pressure", "0.8", "barg"), row("Pumped fluid", "Water"),
            row("Casing material", "Cast iron"), row("Shaft seal", "Mechanical seal")]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Datasheet"
    ws["A1"] = "END SUCTION PUMP DATASHEET"
    ws["A2"], ws["B2"] = "Doc No.", "DS-0012-P"
    ws["A3"], ws["B3"] = "Tag No.", "SYN-P-0012"
    ws.append([])
    ws.append(["Item", "Unit", "Value"])
    for r in rows:
        ws.append([r["field"], r["unit"] or "", float(r["value"]) if _is_number(r["value"]) else r["value"]])
    ws.append(["Impeller diameter", "mm", "By Vendor"])
    ws.merge_cells("A1:C1")
    stamp = datetime.datetime(2026, 1, 1)
    wb.properties.created = stamp
    wb.properties.modified = stamp
    wb.properties.creator = "synthetic"
    buf = io.BytesIO()
    wb.save(buf)
    (OUT / name).write_bytes(normalised_zip(buf.getvalue()))
    record(name, equipment="end suction pump", layout="Excel workbook: Item | Unit | Value",
           expected=rows, forbidden=["Impeller diameter"])


def _is_number(text: str) -> bool:
    return re.fullmatch(r"-?\d+(?:\.\d+)?", text) is not None


def _docx(paragraphs: list[str], table: list[list[str]]) -> bytes:
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

    def esc(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def para(t: str) -> str:
        return f"<w:p><w:r><w:t xml:space=\"preserve\">{esc(t)}</w:t></w:r></w:p>"

    rows = "".join(
        "<w:tr>" + "".join(f"<w:tc><w:tcPr><w:tcW w:w=\"3000\" w:type=\"dxa\"/></w:tcPr>{para(c)}</w:tc>"
                           for c in cells) + "</w:tr>" for cells in table)
    border = "".join(f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
                     for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
    body = ("".join(para(p) for p in paragraphs)
            + f"<w:tbl><w:tblPr><w:tblBorders>{border}</w:tblBorders></w:tblPr>{rows}</w:tbl>"
            + para("") + "<w:sectPr/>")
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" Target="word/document.xml"/></Relationships>'),
        "word/document.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {ns}>'
            f"<w:body>{body}</w:body></w:document>"),
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for part, text in parts.items():
            member = zipfile.ZipInfo(part, date_time=ZIP_TIME)
            member.compress_type = zipfile.ZIP_DEFLATED
            member.external_attr = 0o644 << 16
            member.create_system = 3   # ZipInfo stamps the host OS (0 on Windows); pin it
            z.writestr(member, text.encode("utf-8"))
    return out.getvalue()


def ds13_heater_docx():
    name = "ds13_heater.docx"
    rows = [row("Rated power", "36", "kW"), row("Supply voltage", "400", "V"),
            row("Number of phases", "3"), row("Design pressure", "10", "barg"),
            row("Design temperature", "250", "°C"), row("Watt density", "3.5", "W/cm2"),
            row("Element sheath material", "Incoloy 800"), row("Terminal box protection", "IP66")]
    table = [["Description", "Value"]] + [[r["field"], printed(r)] for r in rows] + [
        ["Thermostat setting", ""]]
    (OUT / name).write_bytes(_docx(
        ["ELECTRIC PROCESS HEATER DATASHEET", "Doc No.: DS-0013-H", "Tag No.: SYN-H-0001"], table))
    record(name, equipment="electric heater", layout="Word document with a two-column table",
           expected=rows, forbidden=["Thermostat setting"])


def ds14_blanks_by_vendor():
    name = "ds14_blanks_by_vendor.pdf"
    rows = [row("Air flow", "36000", "m3/h"), row("Static pressure", "2.5", "kPa"),
            row("Fan speed", "1450", "rpm"), row("Casing material", "Galvanised steel")]
    blanks = [("Motor power", "By Vendor"), ("Impeller diameter", "By Vendor"),
              ("Bearing type", "BY VENDOR"), ("Blade material", "TBA"),
              ("Sound power level", ""), ("Weight", "")]
    doc = pymupdf.open(); page = doc.new_page(width=A4[0], height=A4[1])
    title_block(page, "DS-0014-FN", "SYN-FN-0001", "CENTRIFUGAL FAN DATASHEET")
    body = []
    for r, b in zip(rows + [None] * len(blanks), blanks + [None] * len(rows)):
        if r is not None:
            body.append([r["field"], printed(r)])
        if b is not None:
            body.append([b[0], b[1]])
    ruled_table(page, 110, [240, 200], body)
    save_pdf(doc, name)
    record(name, equipment="centrifugal fan",
           layout="ruled table where most fields are 'By Vendor', 'TBA' or empty",
           expected=rows, forbidden=[b[0] for b in blanks])


BUILDERS = (ds01_pump_ruled, ds02_psv_unruled, ds03_hx_two_column_form,
            ds04_control_valve_req_off, ds05_motor_units_grid, ds06_transmitter_odd_headers,
            ds07_gate_valve_free_text, ds08_tank_merged_cells, ds09_rotated_page,
            ds10_compressor_multipage, ds11_flowmeter_scanned, ds12_pump_xlsx,
            ds13_heater_docx, ds14_blanks_by_vendor)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    KEY.clear()
    for build in BUILDERS:
        build()
    key = {
        "version": 1,
        "note": ("MADE-UP datasheets for measuring datasheet readers. Every field and "
                 "value is invented. Written by scripts/make_datasheet_bench.py - edit "
                 "that script and re-run it, never this file."),
        "files": KEY,
    }
    # write_bytes, not write_text: text mode turns "\n" into "\r\n" on Windows,
    # so the committed (LF) file and a fresh run would differ there.
    (OUT / "answer_key.json").write_bytes(
        (json.dumps(key, indent=1, ensure_ascii=False, sort_keys=False) + "\n").encode("utf-8"))
    total = sum(p.stat().st_size for p in OUT.iterdir())
    print(f"wrote {len(KEY)} datasheets + answer_key.json to {OUT.relative_to(REPO)} "
          f"({total / 1024:.0f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
