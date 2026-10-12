"""A synthetic vessel datasheet in the layouts a real one uses - made-up values only.

Five pages, one per layout the owner's run showed rejected pairs on
(2026-09-26, aggregate only): a cover with a title block and revision table,
a contents page, a drawing with a ruled design-data box and a title block, a
ruled nozzle schedule, and a data page with a row-number ruler down the
margin. No client text: every name, number and value here is invented.

`REAL_PAIRS` lists, per page, the label/value pairs an engineer would expect
read from that page. `NOT_FIELDS` lists what must NOT become a fact (title
block, revision history, contents entries, sheet numbers).
"""
from __future__ import annotations

import pymupdf

W, H = 595, 842


def _grid(page, x0, y0, widths, rows, row_h=18, size=8):
    x1 = x0 + sum(widths)
    for i in range(len(rows) + 1):
        page.draw_line((x0, y0 + i * row_h), (x1, y0 + i * row_h), width=0.6)
    x = x0
    for w in [0, *widths]:
        x += w
        page.draw_line((x, y0), (x, y0 + len(rows) * row_h), width=0.6)
    for r, cells in enumerate(rows):
        x = x0
        for w, text in zip(widths, cells, strict=True):
            if text:
                page.insert_text((x + 3, y0 + r * row_h + 12), text, fontsize=size)
            x += w


def _title_block(page, sheet: str):
    _grid(page, 300, 740, [110, 145], [
        ["CLIENT", "EXAMPLE OPERATOR"],
        ["DOCUMENT NO.", "EX-100-DS-0001"],
        ["REV", "B"],
        ["SHEET", sheet],
    ], row_h=16, size=7)


def cover(pdf):
    page = pdf.new_page(width=W, height=H)
    page.insert_text((180, 120), "MECHANICAL DATASHEET", fontsize=16)
    page.insert_text((180, 150), "HORIZONTAL SEPARATOR", fontsize=12)
    _grid(page, 60, 200, [160, 300], [
        ["EQUIPMENT", "HORIZONTAL SEPARATOR"],
        ["TAG NO.", "V-9001"],
        ["DESIGN CODE", "ASME VIII DIV. 1"],
        ["SERVICE", "PRODUCED WATER"],
    ])
    _grid(page, 60, 560, [40, 200, 90, 90, 90], [
        ["REV", "DESCRIPTION", "PREPARED", "CHECKED", "APPROVED"],
        ["A", "ISSUED FOR REVIEW", "A. AUTHOR", "B. CHECKER", "C. LEAD"],
        ["B", "ISSUED FOR DESIGN", "A. AUTHOR", "B. CHECKER", "C. LEAD"],
    ])
    _title_block(page, "1 OF 5")


def contents(pdf):
    page = pdf.new_page(width=W, height=H)
    page.insert_text((60, 90), "CONTENTS", fontsize=12)
    for i, (title, p) in enumerate([("GENERAL", 3), ("DESIGN DATA", 3),
                                    ("NOZZLE SCHEDULE", 4), ("PROCESS DATA", 5)], start=1):
        page.insert_text((60, 120 + 22 * i), f"{i}. {title} " + "." * 40 + f" {p}", fontsize=10)
    _title_block(page, "2 OF 5")


def drawing(pdf):
    page = pdf.new_page(width=W, height=H)
    page.draw_rect(pymupdf.Rect(80, 120, 420, 260), width=1.2)      # the vessel
    page.draw_circle((80, 190), 70, width=1.2)
    page.insert_text((200, 110), "3000", fontsize=8)
    page.insert_text((180, 280), "N1", fontsize=8)
    page.insert_text((320, 280), "N2", fontsize=8)
    page.insert_text((60, 330), "DESIGN DATA", fontsize=10)
    _grid(page, 60, 340, [180, 120], [
        ["DESIGN PRESSURE", "10 barg"],
        ["OPERATING PRESSURE", "8 barg"],
        ["DESIGN TEMPERATURE", "120 C"],
        ["HYDROTEST PRESSURE", "13 barg"],
        ["CORROSION ALLOWANCE", "3 mm"],
        ["SHELL MATERIAL", "SA-516 GR.70"],
        ["RADIOGRAPHY", "FULL"],
        ["PWHT", "YES"],
        ["EMPTY WEIGHT", "4500 kg"],
    ])
    _title_block(page, "3 OF 5")


def nozzles(pdf):
    page = pdf.new_page(width=W, height=H)
    page.insert_text((60, 90), "NOZZLE SCHEDULE", fontsize=12)
    _grid(page, 60, 110, [50, 40, 60, 60, 50, 150], [
        ["MARK", "QTY", "SIZE", "RATING", "FACING", "SERVICE"],
        ["N1", "1", "6", "CL300", "RF", "INLET"],
        ["N2", "1", "4", "CL300", "RF", "GAS OUTLET"],
        ["N3", "2", "2", "CL300", "RF", "DRAIN"],
        ["M1", "1", "24", "CL300", "RF", "MANWAY"],
    ])
    _title_block(page, "4 OF 5")


def data_page(pdf):
    page = pdf.new_page(width=W, height=H)
    page.insert_text((60, 70), "PROCESS DATA", fontsize=12)
    rows = [("FLUID", "", "PRODUCED WATER"), ("OPERATING TEMPERATURE", "C", "90"),
            ("DENSITY", "kg/m3", "1020"), ("VISCOSITY", "cP", "0.8"),
            ("LIQUID LEVEL (NLL)", "mm", "750"), ("INSULATION", "", "NONE")]
    for i, (label, unit, value) in enumerate(rows, start=1):
        y = 100 + 20 * i
        page.insert_text((30, y), str(i), fontsize=7)                 # the margin ruler
        page.insert_text((60, y), label, fontsize=9)
        page.insert_text((300, y), unit, fontsize=9)
        page.insert_text((380, y), value, fontsize=9)
    _title_block(page, "5 OF 5")


LAYOUTS = (cover, contents, drawing, nozzles, data_page)

#: What an engineer expects read, per page (label fragment -> value fragment).
REAL_PAIRS = {
    1: {"design code": "asme viii div. 1"},
    3: {"design pressure": "10 barg", "operating pressure": "8 barg", "design temperature": "120 c",
        "hydrotest pressure": "13 barg", "corrosion allowance": "3 mm", "empty weight": "4500 kg",
        "shell material": "sa-516 gr.70", "radiography": "full", "pwht": "yes"},
    4: {"n1 size": "6", "n2 service": "gas outlet", "m1 rating": "cl300"},
    5: {"operating temperature": "90 c", "density": "1020 kg/m3", "liquid level nll": "750 mm"},
}

#: Real pairs the audit leaves UNREAD, each with its reason (see
#: docs/extraction-filter-audit.md): free text a caption shares its shape with,
#: and a unit the unit table does not know.
KNOWN_GAPS = {"service": "free text", "equipment": "free text", "fluid": "free text",
              "viscosity": "cP is not in the unit table"}

#: What must never be a fact.
NOT_FIELDS = ("a. author", "b. checker", "issued for", "1 of 5", "ex-100-ds-0001",
              "general", "nozzle schedule")


def build(path) -> int:
    pdf = pymupdf.open()
    for layout in LAYOUTS:
        layout(pdf)
    pdf.save(str(path))
    count = pdf.page_count
    pdf.close()
    return count
