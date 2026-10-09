"""The P1 invented corpus: fourteen made-up standards, no client text.

Every name, number and sentence here is invented. The set is small on purpose
and built to hit the failure classes found in this project: a reworded
question, an abbreviation, a document named in the question, the same
boilerplate in two documents, a value that lives in a table, a condition that
limits a rule, an old revision beside a new one, and a topic one document has
and another does not.

Version 2 (2026-10-08) added STD-G-007 to STD-K-010. Each one puts a near miss
next to an existing topic (a tank's water fill hold beside a vessel's test
hold, a fan's vibration limit beside a pump's, an impulse line's test pressure
beside a vessel's) and carries values written the way real standards write
them: a negative temperature, a signed range, a decimal comma and a power of
ten. None of them mentions a crane, a warranty, a colour or a flange, so the
version 1 unanswerable questions stay unanswerable.

Version 3 (2026-10-09) added STD-L-011 and STD-M-012 for #602 and #610: a
question carrying a describing word no document prints, and a standard whose
first page is a foreword and revision history. They too avoid a crane, a
warranty, a colour and a flange (P1-27 depends on that), and the bolting
standard is about pipe supports, not flanged joints, for that reason.

Version 4 (2026-10-09) added STD-N-013: a composition table that prints the
bare alloy code under its UNS column, for a question that writes the prefix.

`build(folder)` writes the PDFs deterministically. Page numbers below are the
ground truth the question set points at; `questions.json` is checked against
this text by `check_labels` so a label can never drift from the corpus.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf

# filename -> list of pages -> list of lines
DOCS: dict[str, list[list[str]]] = {
    "STD-A-001.pdf": [
        [
            "STD-A-001 Rotating Equipment Inspection and Vibration, Revision 1",
            "1 Scope",
            "1.1 This standard covers centrifugal pumps in continuous service.",
            "1.2 It does not cover reciprocating pumps.",
            "2 Abbreviations",
            "RMS means root mean square.",
            "MTBF means mean time between failures.",
        ],
        [
            "3 Inspection",
            "3.1 Each pump shall be inspected at intervals not exceeding 4000",
            "operating hours.",
            "3.2 Any exceedance shall be reported to the area engineer before the",
            "pump is returned to service.",
        ],
        [
            "4 Vibration",
            "4.1 Vibration measured at the bearing housing shall not exceed",
            "3.0 mm/s RMS during continuous operation at rated flow.",
            "4.2 Readings shall be taken monthly.",
            "Table 2 Bearing temperature limits",
            "Item  Alarm  Trip",
            "Drive end bearing  85 degC  95 degC",
            "Non drive end bearing  80 degC  90 degC",
        ],
    ],
    "STD-A-001-REV0.pdf": [
        [
            "STD-A-001 Rotating Equipment Inspection and Vibration, Revision 0",
            "This revision was replaced by Revision 1.",
            "4 Vibration",
            "4.1 Vibration measured at the bearing housing shall not exceed",
            "2.5 mm/s RMS during continuous operation at rated flow.",
        ],
    ],
    "STD-B-002.pdf": [
        [
            "STD-B-002 Protective Coating of Piping, Revision 2",
            "1 Scope",
            "1.1 This standard applies to carbon steel piping only.",
            "1.2 Stainless steel piping is not coated under this standard.",
            "2 Abbreviations",
            "DFT means dry film thickness.",
        ],
        [
            "3 Surface preparation",
            "3.1 Surfaces shall be blast cleaned to Sa 2.5 before coating.",
            "3.2 Coating shall be applied within 4 hours of blast cleaning.",
        ],
        [
            "4 Coating system",
            "4.1 The minimum DFT of the primer coat shall be 250 micrometres.",
            "4.2 The finish coat shall be applied after the primer has cured.",
        ],
    ],
    "STD-C-003.pdf": [
        [
            "STD-C-003 Pressure Vessel Testing and Heat Treatment, Revision 3",
            "1 Scope",
            "1.1 This standard covers fabricated pressure vessels.",
            "2 Abbreviations",
            "PWHT means post weld heat treatment.",
            "MAWP means maximum allowable working pressure.",
        ],
        [
            "6 Heat treatment",
            "6.1 PWHT shall be carried out when the shell thickness exceeds",
            "32 mm.",
            "6.2 The holding temperature shall be recorded on a chart.",
        ],
        [
            "7 Hydrostatic test",
            "7.1 The hydrostatic test pressure shall be 1.3 times the design",
            "pressure.",
            "7.2 The test pressure shall be held for 30 minutes.",
            "7.3 Any exceedance shall be reported to the area engineer.",
        ],
    ],
    "STD-D-004.pdf": [
        [
            "STD-D-004 Electrical Enclosure Protection, Revision 1",
            "1 Scope",
            "1.1 This standard covers electrical enclosures installed outdoors.",
            "2 Protection rating",
            "2.1 Outdoor enclosures shall have a minimum rating of IP66.",
            "2.2 The design ambient temperature shall be 50 degC.",
        ],
        [
            "3 Cable entries",
            "3.1 Unused cable entries shall be closed with certified plugs.",
        ],
    ],
    "STD-E-005.pdf": [
        [
            "STD-E-005 Fire Water Pump Testing, Revision 1",
            "1 Scope",
            "1.1 This standard covers diesel driven fire water pumps.",
            "2 Weekly test",
            "2.1 Each pump shall be run for 30 minutes every week.",
        ],
        [
            "3 Annual test",
            "3.1 Each pump shall deliver 150 percent of rated flow at not less",
            "than 65 percent of rated head.",
            "3.2 Any exceedance shall be reported to the area engineer.",
        ],
    ],
    "STD-F-006.pdf": [
        [
            "STD-F-006 Noise Control, Revision 1",
            "1 Scope",
            "1.1 This standard covers noise exposure in process areas.",
        ],
        [
            "4 Limits",
            "4.1 Areas where noise exceeds 85 dB(A) shall be marked as hearing",
            "protection zones.",
            "4.2 Noise exposure shall not exceed 90 dB(A) for any worker.",
        ],
    ],
    "STD-G-007.pdf": [
        [
            "STD-G-007 Heat Tracing and Winterisation, Revision 1",
            "1 Scope",
            "1.1 This standard covers heat tracing and insulation of outdoor process",
            "lines.",
            "2 Abbreviations",
            "LDT means lowest design temperature.",
        ],
        [
            "3 Design temperatures",
            "3.1 The lowest design temperature for outdoor equipment shall be -29 degC.",
            "3.2 Heat tracing shall hold the process fluid between +5 degC and +15 degC.",
        ],
        [
            "4 Insulation",
            "4.1 The thermal conductivity of the insulation shall not exceed",
            "0,040 W/(m.K) at a mean temperature of 10 degC.",
            "4.2 Insulation thickness shall be 40 mm to 80 mm depending on line size.",
        ],
    ],
    "STD-H-008.pdf": [
        [
            "STD-H-008 Instrument Calibration and Testing, Revision 2",
            "1 Scope",
            "1.1 This standard covers pressure and flow instruments.",
            "2 Abbreviations",
            "URV means upper range value.",
        ],
        [
            "5 Accuracy",
            "5.1 Pressure transmitters shall be accurate to within +/-0.25 percent of",
            "span.",
            "5.2 Zero drift shall stay within -0,5 kPa to +0,5 kPa per year.",
            "5.3 The insulation resistance of signal cables shall be at least",
            "1.0 x 10^9 ohm.",
        ],
        [
            "6 Calibration interval",
            "6.1 Safety critical instruments shall be calibrated every 12 months.",
            "6.2 Other instruments shall be calibrated every 24 months.",
            "7 Impulse lines",
            "7.1 Impulse lines shall be pressure tested at 1.5 times the design",
            "pressure.",
        ],
    ],
    "STD-J-009.pdf": [
        [
            "STD-J-009 Atmospheric Storage Tank Testing and Inspection, Revision 1",
            "1 Scope",
            "1.1 This standard covers welded atmospheric storage tanks.",
        ],
        [
            "4 Water fill test",
            "4.1 Each new tank shall be filled with water to the design liquid level",
            "and held full for 24 hours.",
            "4.2 Settlement shall be measured at eight points around the shell.",
        ],
        [
            "5 Inspection",
            "5.1 The interval between external inspections shall not exceed 5 years.",
            "5.2 Bottom plates shall be renewed when the remaining thickness is less",
            "than 2.5 mm.",
        ],
    ],
    "STD-K-010.pdf": [
        [
            "STD-K-010 Air Cooled Heat Exchanger Fans, Revision 1",
            "1 Scope",
            "1.1 This standard covers the fans of air cooled heat exchangers.",
            "2 Blades",
            "2.1 Blade pitch shall be set within 0.5 degrees of the design angle.",
        ],
        [
            "3 Vibration",
            "3.1 Vibration measured at the fan bearing shall not exceed 6.0 mm/s",
            "RMS.",
            "3.2 Readings shall be taken weekly.",
        ],
    ],
    # Version 3 (#602, #610). A clause answerable with or without a describing
    # word the corpus never prints ("Code-certified"), and a standard whose
    # first page is front matter - a foreword and a revision history that
    # repeat a bolting question's every word and state none of its values.
    "STD-L-011.pdf": [
        [
            "STD-L-011 Relief Valve Capacity, Revision 0",
            "1 Scope",
            "1.1 This standard covers the rated capacity of relief valves in liquid service.",
        ],
        [
            "5 Liquid Service",
            "5.1 Relief valves in liquid service shall reach full rated capacity",
            "at an overpressure of 10 percent of the set pressure.",
            "5.2 Each relief valve shall carry a nameplate stating its set pressure.",
        ],
    ],
    "STD-M-012.pdf": [
        [
            "STD-M-012 Pipe Support Bolting, Revision 3",
            "Foreword",
            "This revision replaces Revision 2.",
            "Revision history",
            "Revision 2 changed the bolting material requirements for pipe supports.",
            "Revision 3 corrected the bolting material required for pipe supports in Table 2.",
        ],
        [
            "4 Bolting",
            "4.1 Bolting material for pipe supports shall be alloy steel stud bolts",
            "to grade B7 with grade 2H heavy hex nuts.",
            "4.2 Bolts shall extend at least two threads beyond the nut.",
        ],
    ],
    # Version 4: a materials table that prints the bare code ("N06625")
    # under its UNS column, asked about with the prefix ("UNS N06625").
    "STD-N-013.pdf": [
        [
            "STD-N-013 Sour Service Alloy Selection, Revision 0",
            "1 Scope",
            "1.1 This standard limits the composition of corrosion resistant alloys for sour service.",
            "2 Composition",
            "2.1 Nickel alloys shall meet the composition limits in Table 1.",
        ],
        [
            "Table 1 Composition limits of nickel alloys",
            "UNS  C max  Cr  Ni min",
            "N06625  0.08  20.0-23.0  58.0",
            "N08825  0.04  19.5-23.5  38.0",
            "N10276  0.01  14.5-16.5  51.0",
        ],
    ],
}


def build(folder: Path) -> list[Path]:
    """Write every PDF into `folder`, in a fixed order, and return the paths."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in sorted(DOCS):
        pdf = pymupdf.open()
        for lines in DOCS[name]:
            page = pdf.new_page()
            for i, line in enumerate(lines):
                page.insert_text((72, 100 + i * 18), line, fontsize=11)
        path = folder / name
        pdf.save(str(path))
        pdf.close()
        paths.append(path)
    return paths


def page_text(filename: str, page: int) -> str:
    return " ".join(DOCS[filename][page - 1])
