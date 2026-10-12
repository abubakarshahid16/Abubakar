"""A planted-defect CRS benchmark - made-up standards and datasheets only.

CRS quick wins (2026-09-27). Rebuilt from the CRS audit's harness
(audit crs.md section 3): two synthetic company standards (a vessel standard
with 15 obligation sentences, a pump standard with 8) and two datasheets with
KNOWN problems planted in them - a single-tag vessel sheet with 11 and a
two-tag pump enquiry sheet ("* = vendor to advise") with 8. No client text:
every name, number and value here is invented.

`GOLD` is the answer key an engineer would write: one issue per planted
problem, the datasheet field it is about, and the value the sheet states.
`score` measures a CRS against it:

  * ISSUE RECALL - gold issues named by an ITEMISED row (a summary row
    naming none of them does not count) that also carries the stated value;
  * ROW PRECISION - rows that match at least one gold issue and state no
    forbidden value (the wrongly parsed limit of a clause), out of all rows.

Both are AUTOMATED approximations of an engineer's judgement, labelled as
such wherever they are reported. The audit's own baseline, judged by hand on
the same documents, was recall 4/19 and precision 4/7.
"""
from __future__ import annotations

import re

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


def _lines(page, y, lines, size=9, x=60, step=14):
    for ln in lines:
        page.insert_text((x, y), ln, fontsize=size)
        y += step
    return y


def vessel_standard(path):
    pdf = pymupdf.open()
    p = pdf.new_page(width=W, height=H)
    p.insert_text((60, 50), "SAES-D-901   Pressure Vessel Design   Issue 3", fontsize=8)
    y = _lines(p, 90, ["SAES-D-901", "Pressure Vessel Design Requirements"], size=14, step=22)
    y = _lines(p, y + 10, [
        "1  Scope",
        "1.1  This standard defines the minimum mandatory requirements for the design of",
        "     pressure vessels, drums and separators.",
        "2  Conflicts and Deviations",
        "2.1  Any conflicts between this standard and other applicable standards shall be",
        "     resolved in writing by the Company.",
        "3  References",
        "3.1  ASME SEC VIII DIV 1, Rules for Construction of Pressure Vessels.",
        "4  Design",
        "4.1  The internal design pressure shall be according to the following table:",
    ])
    _grid(p, 60, y, [220, 240], [
        ["Maximum Operating Pressure (kPa)", "Internal Design Pressure (kPa)"],
        ["Up to 1800", "MOP + 170"],
        ["Over 1800 up to 6900", "The greater of 1.1 x MOP and MOP + 170"],
    ], size=8)
    y += 70
    _lines(p, y, [
        "4.2  The design temperature shall be at least 28 C higher than the maximum operating",
        "     temperature.",
        "4.3  The corrosion allowance for carbon steel vessels shall be not less than 3 mm.",
        "4.4  The hydrostatic test pressure shall be at least 1.3 times the design pressure.",
        "4.5  Manways shall have a minimum inside diameter of 450 mm.",
        "4.6  Nozzle flanges shall have a minimum pressure rating of Class 300.",
        "4.7  Nozzle size shall not be less than 50 mm.",
    ])
    p2 = pdf.new_page(width=W, height=H)
    p2.insert_text((60, 50), "SAES-D-901   Pressure Vessel Design   Issue 3", fontsize=8)
    _lines(p2, 90, [
        "5  Fabrication and Inspection",
        "5.1  Full radiography shall be performed on all butt welds of vessels in sour service.",
        "5.2  Post weld heat treatment shall be performed when the shell thickness exceeds 38 mm.",
        "5.3  The Vendor shall submit material test certificates for all pressure parts.",
        "5.4  The noise level of associated equipment shall not exceed 85 dB(A) at 1 m.",
        "5.5  The empty weight of the vessel shall be stated on the datasheet.",
        "6  Documentation",
        "6.1  The Vendor shall submit general arrangement drawings for Company approval.",
        "6.2  The maximum allowable working pressure shall be not less than the design pressure.",
    ])
    pdf.save(path)


def pump_standard(path):
    pdf = pymupdf.open()
    p = pdf.new_page(width=W, height=H)
    p.insert_text((60, 50), "SAES-G-905   Centrifugal Pumps   Issue 2", fontsize=8)
    _lines(p, 90, ["SAES-G-905", "Centrifugal Pumps"], size=14, step=22)
    _lines(p, 150, [
        "1  Scope",
        "1.1  This standard covers centrifugal pumps for hydrocarbon and water services.",
        "4  Design",
        "4.1  The noise level shall not exceed 85 dB(A) at 1 m from the pump.",
        "4.2  The NPSH margin shall be at least 1 m above the NPSH required.",
        "4.3  Pump rated speed shall not exceed 3600 rpm.",
        "4.4  Overall vibration shall not exceed 3.0 mm/s.",
        "4.5  Mechanical seals shall be in accordance with API 682.",
        "4.6  The minimum continuous stable flow shall not exceed 30 % of rated flow.",
        "4.7  The motor rating shall be at least 110 % of the rated pump power.",
        "5  Inspection",
        "5.1  The Vendor shall submit performance test certificates.",
    ])
    pdf.save(path)


def vessel_sheet(path):
    pdf = pymupdf.open()
    p = pdf.new_page(width=W, height=H)
    p.insert_text((180, 80), "MECHANICAL DATASHEET - KNOCK OUT DRUM", fontsize=12)
    _grid(p, 60, 110, [180, 280], [
        ["TAG NO.", "V-2001"],
        ["SERVICE", "FUEL GAS KNOCK OUT"],
        ["DESIGN CODE", "ASME SEC VIII DIV 1"],
        ["COMPANY SPECIFICATION", "SAES-D-901"],
        ["MATERIAL SPECIFICATION", "NACE MR0175"],
        ["OPERATING PRESSURE", "8 barg"],
        ["DESIGN PRESSURE", "9 barg"],
        ["OPERATING TEMPERATURE", "90 C"],
        ["DESIGN TEMPERATURE", "110 C"],
        ["HYDROTEST PRESSURE", "11 barg"],
        ["MAWP", "9 barg"],
        ["CORROSION ALLOWANCE", "1.5 mm"],
        ["SHELL MATERIAL", "SA-516 GR.70 (CARBON STEEL)"],
        ["SHELL THICKNESS", "42 mm"],
        ["RADIOGRAPHY", "SPOT"],
        ["PWHT", "TBA"],
        ["EMPTY WEIGHT", "*"],
        ["MANWAY SIZE", "400 mm"],
        ["NOISE LEVEL", "88 dB(A)"],
        ["INSULATION", "NONE"],
    ], row_h=18, size=8)
    p2 = pdf.new_page(width=W, height=H)
    p2.insert_text((60, 90), "NOZZLE SCHEDULE", fontsize=12)
    _grid(p2, 60, 110, [50, 40, 60, 60, 50, 150], [
        ["MARK", "QTY", "SIZE", "RATING", "FACING", "SERVICE"],
        ["N1", "1", "150 mm", "CL300", "RF", "INLET"],
        ["N2", "1", "100 mm", "CL150", "RF", "GAS OUTLET"],
        ["N3", "2", "25 mm", "CL300", "RF", "DRAIN"],
    ])
    pdf.save(path)


def pump_sheet(path):
    """Enquiry-form style: label | unit | P-101A | P-101B, '*' = vendor to advise."""
    pdf = pymupdf.open()
    p = pdf.new_page(width=W, height=H)
    p.insert_text((150, 70), "CENTRIFUGAL PUMP DATASHEET", fontsize=12)
    p.insert_text((60, 90), "Applicable specification: SAES-G-905, API 610, API 682", fontsize=8)
    p.insert_text((60, 102), "* = Vendor to advise", fontsize=8)
    _grid(p, 60, 115, [190, 70, 90, 90], [
        ["ITEM", "UNIT", "P-101A", "P-101B"],
        ["RATED FLOW", "m3/h", "120", "120"],
        ["DIFFERENTIAL HEAD", "m", "85", "85"],
        ["NPSH AVAILABLE", "m", "6.5", "6.5"],
        ["NPSH REQUIRED", "m", "*", "*"],
        ["RATED SPEED", "rpm", "3550", "3550"],
        ["NOISE LEVEL", "dB(A)", "*", "*"],
        ["VIBRATION", "mm/s", "3.5", "3.5"],
        ["RATED POWER", "kW", "45", "45"],
        ["MOTOR RATING", "kW", "*", "*"],
        ["MIN CONTINUOUS FLOW", "m3/h", "*", "*"],
        ["DESIGN PRESSURE", "barg", "25", "25"],
        ["DESIGN TEMPERATURE", "C", "80", "80"],
        ["SEAL TYPE", "", "VENDOR TO ADVISE", "VENDOR TO ADVISE"],
    ], row_h=18, size=8)
    pdf.save(path)


DOCUMENTS = {
    "SAES-D-901.pdf": (vessel_standard, "COMPANY_STANDARD"),
    "SAES-G-905.pdf": (pump_standard, "COMPANY_STANDARD"),
    "DS-V-2001.pdf": (vessel_sheet, "CONTRACTOR_SUBMITTAL"),
    "DS-P-101.pdf": (pump_sheet, "CONTRACTOR_SUBMITTAL"),
}

_BLANK = r"(\*|blank|vendor to advise|tba|to be provided)"

#: (issue id, field pattern, pattern the stated value must match, forbidden
#: pattern or None). Patterns are case-insensitive, over the row's Page /
#: Section, comment and standard reference together.
GOLD: dict[str, list[tuple[str, str, str, str | None]]] = {
    "DS-V-2001.pdf": [
        ("V-DP design pressure below MOP + 170 kPa (4.1)", r"design pressure", r"9 barg", r"1800"),
        ("V-DT design temperature margin (4.2)", r"design temperature", r"110", None),
        ("V-CA corrosion allowance 1.5 < 3 mm (4.3)", r"corrosion allowance", r"1\.5", None),
        ("V-HT hydrotest 11 < 1.3 x 9 barg (4.4)", r"hydro", r"\b11\b", None),
        ("V-MW manway 400 < 450 mm (4.5)", r"manway", r"400", None),
        ("V-FL N2 flange CL150 < Class 300 (4.6)", r"\bn2\b", r"cl ?150", None),
        ("V-NZ N3 nozzle 25 < 50 mm (4.7)", r"\bn3\b", r"\b25\b", None),
        ("V-RT radiography SPOT vs full, sour (5.1)", r"radiograph", r"spot", None),
        ("V-PWHT PWHT TBA with 42 mm shell (5.2)", r"pwht|post weld", _BLANK, None),
        ("V-NOISE noise 88 > 85 dB(A) (5.4)", r"noise", r"\b88\b", None),
        ("V-EW empty weight not stated (5.5)", r"empty weight", _BLANK, None),
    ],
    "DS-P-101.pdf": [
        ("P-NOISE noise level * (4.1)", r"noise", _BLANK, None),
        ("P-NPSH NPSH required * (4.2)", r"npsh", _BLANK, None),
        ("P-VIB vibration 3.5 > 3.0 mm/s (4.4)", r"vibration", r"3\.5", None),
        ("P-SEAL seal type vendor to advise (4.5)", r"seal", _BLANK, None),
        ("P-MINF min continuous flow * (4.6)", r"min(imum)? continuous", _BLANK, None),
        ("P-MOTOR motor rating * (4.7)", r"motor", _BLANK, None),
        ("P-OPT operating temperature not stated", r"operating temperature",
         r"not found|not state", None),
        ("P-REV no revision block", r"revision block", r"no revision block", None),
    ],
}


def _text(row: dict) -> str:
    return " ".join(str(row.get(k) or "") for k in
                    ("page_section", "comment", "standard_reference")).lower()


def matches(row: dict, issue: tuple[str, str, str, str | None]) -> bool:
    _name, field, value, forbid = issue
    text = _text(row)
    return (re.search(field, text) is not None and re.search(value, text) is not None
            and not (forbid and re.search(forbid, text)))


def score(rows_by_sheet: dict[str, list[dict]]) -> dict:
    """Recall and precision of CRS rows against `GOLD`, per sheet and total."""
    out: dict = {"sheets": {}}
    found_total = gold_total = good_total = rows_total = 0
    for sheet, gold in GOLD.items():
        rows = rows_by_sheet.get(sheet, [])
        found = [g[0] for g in gold if any(matches(r, g) for r in rows)]
        good = [r for r in rows if any(matches(r, g) for g in gold)]
        out["sheets"][sheet] = {"issues": len(gold), "found": found,
                                "missed": [g[0] for g in gold if g[0] not in found],
                                "rows": len(rows), "correct_rows": len(good)}
        found_total += len(found)
        gold_total += len(gold)
        good_total += len(good)
        rows_total += len(rows)
    out.update({"issues_found": found_total, "issues_total": gold_total,
                "recall": round(found_total / gold_total, 3) if gold_total else None,
                "correct_rows": good_total, "rows_total": rows_total,
                "precision": round(good_total / rows_total, 3) if rows_total else None})
    return out
